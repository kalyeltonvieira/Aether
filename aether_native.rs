use std::mem::size_of;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::slice;

const ABI_VERSION: u32 = 2;
const ERR_NULL: i64 = -1;
const ERR_INVALID: i64 = -2;
const ERR_ALLOC: i64 = -3;
const ERR_PANIC: i64 = -4;
const ERR_OVERFLOW: i64 = -5;
const ERR_BUFFER_TOO_SMALL: i64 = -6;

pub struct Graph {
    rows: Vec<Vec<u32>>,
    marks: Vec<u32>,
    stack: Vec<u32>,
    epoch: u32,
    edges: usize,
}

impl Graph {
    fn new(n: usize) -> Result<Self, i64> {
        if n == 0 || n > u32::MAX as usize {
            return Err(ERR_INVALID);
        }

        let mut rows = Vec::new();
        rows.try_reserve_exact(n).map_err(|_| ERR_ALLOC)?;
        rows.resize_with(n, Vec::new);

        let mut marks = Vec::new();
        marks.try_reserve_exact(n).map_err(|_| ERR_ALLOC)?;
        marks.resize(n, 0);

        Ok(Self {
            rows,
            marks,
            stack: Vec::new(),
            epoch: 0,
            edges: 0,
        })
    }

    fn valid_node(&self, node: u32) -> bool {
        (node as usize) < self.rows.len()
    }

    fn add(&mut self, u: u32, v: u32) -> Result<bool, i64> {
        if !self.valid_node(u) || !self.valid_node(v) {
            return Err(ERR_INVALID);
        }
        let row = &mut self.rows[u as usize];
        if row.contains(&v) {
            return Ok(false);
        }
        let next_edges = self.edges.checked_add(1).ok_or(ERR_OVERFLOW)?;
        row.try_reserve(1).map_err(|_| ERR_ALLOC)?;
        row.push(v);
        self.edges = next_edges;
        Ok(true)
    }

    // Validate the complete input and reserve all row capacity before changing
    // logical graph state. Duplicate pairs are accepted and counted once.
    fn add_many(&mut self, pairs: &[u32]) -> Result<i64, i64> {
        if pairs.len() % 2 != 0 {
            return Err(ERR_INVALID);
        }
        let pair_count = pairs.len() / 2;
        self.edges.checked_add(pair_count).ok_or(ERR_OVERFLOW)?;

        let mut needed = Vec::new();
        needed
            .try_reserve_exact(self.rows.len())
            .map_err(|_| ERR_ALLOC)?;
        needed.resize(self.rows.len(), 0usize);

        for pair in pairs.chunks_exact(2) {
            let (u, v) = (pair[0], pair[1]);
            if !self.valid_node(u) || !self.valid_node(v) {
                return Err(ERR_INVALID);
            }
            needed[u as usize] = needed[u as usize]
                .checked_add(1)
                .ok_or(ERR_OVERFLOW)?;
        }

        for (row, additional) in self.rows.iter_mut().zip(needed.iter()) {
            row.try_reserve(*additional).map_err(|_| ERR_ALLOC)?;
        }

        let mut changed = 0usize;
        for pair in pairs.chunks_exact(2) {
            let row = &mut self.rows[pair[0] as usize];
            if !row.contains(&pair[1]) {
                row.push(pair[1]);
                changed = changed.checked_add(1).ok_or(ERR_OVERFLOW)?;
            }
        }
        self.edges = self.edges.checked_add(changed).ok_or(ERR_OVERFLOW)?;
        i64::try_from(changed).map_err(|_| ERR_OVERFLOW)
    }

    fn remove(&mut self, u: u32, v: u32) -> Result<bool, i64> {
        if !self.valid_node(u) || !self.valid_node(v) {
            return Err(ERR_INVALID);
        }
        let row = &mut self.rows[u as usize];
        let Some(i) = row.iter().position(|&x| x == v) else {
            return Ok(false);
        };
        row.swap_remove(i);
        self.edges -= 1;
        Ok(true)
    }

    fn remove_many(&mut self, pairs: &[u32]) -> Result<i64, i64> {
        if pairs.len() % 2 != 0 {
            return Err(ERR_INVALID);
        }
        for pair in pairs.chunks_exact(2) {
            if !self.valid_node(pair[0]) || !self.valid_node(pair[1]) {
                return Err(ERR_INVALID);
            }
        }
        let mut changed = 0usize;
        for pair in pairs.chunks_exact(2) {
            if self.remove(pair[0], pair[1])? {
                changed = changed.checked_add(1).ok_or(ERR_OVERFLOW)?;
            }
        }
        i64::try_from(changed).map_err(|_| ERR_OVERFLOW)
    }

    fn reachable(&mut self, source: u32, target: u32) -> Result<bool, i64> {
        if !self.valid_node(source) || !self.valid_node(target) {
            return Err(ERR_INVALID);
        }
        if source == target {
            return Ok(true);
        }

        self.epoch = self.epoch.wrapping_add(1);
        if self.epoch == 0 {
            self.marks.fill(0);
            self.epoch = 1;
        }
        let epoch = self.epoch;
        self.stack.clear();
        self.stack
            .try_reserve(self.rows.len())
            .map_err(|_| ERR_ALLOC)?;
        self.stack.push(source);
        self.marks[source as usize] = epoch;

        while let Some(u) = self.stack.pop() {
            for &v in &self.rows[u as usize] {
                if v == target {
                    return Ok(true);
                }
                if self.marks[v as usize] != epoch {
                    self.marks[v as usize] = epoch;
                    self.stack.push(v);
                }
            }
        }
        Ok(false)
    }

    fn memory_bytes(&self) -> Option<usize> {
        let mut total = size_of::<Self>()
            .checked_add(self.rows.capacity().checked_mul(size_of::<Vec<u32>>())?)?
            .checked_add(self.marks.capacity().checked_mul(size_of::<u32>())?)?
            .checked_add(self.stack.capacity().checked_mul(size_of::<u32>())?)?;
        for row in &self.rows {
            total = total.checked_add(row.capacity().checked_mul(size_of::<u32>())?)?;
        }
        Some(total)
    }
}

fn ffi_i64<F>(operation: F) -> i64
where
    F: FnOnce() -> Result<i64, i64>,
{
    match catch_unwind(AssertUnwindSafe(operation)) {
        Ok(Ok(value)) => value,
        Ok(Err(code)) => code,
        Err(_) => ERR_PANIC,
    }
}

unsafe fn input_u32_slice<'a>(data: *const u32, length: usize) -> Result<&'a [u32], i64> {
    if length > (isize::MAX as usize) / size_of::<u32>() {
        return Err(ERR_OVERFLOW);
    }
    if length == 0 {
        return Ok(&[]);
    }
    if data.is_null() {
        return Err(ERR_NULL);
    }
    // The caller must provide a readable, aligned allocation of `length` u32s.
    Ok(unsafe { slice::from_raw_parts(data, length) })
}

unsafe fn output_u8_slice<'a>(data: *mut u8, length: usize) -> Result<&'a mut [u8], i64> {
    if length > isize::MAX as usize {
        return Err(ERR_OVERFLOW);
    }
    if length == 0 {
        return Ok(&mut []);
    }
    if data.is_null() {
        return Err(ERR_NULL);
    }
    // The caller must provide a writable allocation of `length` bytes.
    Ok(unsafe { slice::from_raw_parts_mut(data, length) })
}

unsafe fn graph_mut<'a>(ptr: *mut Graph) -> Result<&'a mut Graph, i64> {
    if ptr.is_null() {
        return Err(ERR_NULL);
    }
    // The caller must pass a live handle returned by aether_graph_new exactly
    // once at a time. Arbitrary non-null addresses cannot be validated in C.
    Ok(unsafe { &mut *ptr })
}

unsafe fn graph_ref<'a>(ptr: *const Graph) -> Result<&'a Graph, i64> {
    if ptr.is_null() {
        return Err(ERR_NULL);
    }
    // The caller must pass a live handle returned by aether_graph_new.
    Ok(unsafe { &*ptr })
}

#[no_mangle]
pub extern "C" fn aether_graph_abi_version() -> u32 {
    ABI_VERSION
}

#[no_mangle]
pub extern "C" fn aether_graph_pointer_width() -> u32 {
    (size_of::<usize>() * 8) as u32
}

#[no_mangle]
pub extern "C" fn aether_graph_platform_id() -> u32 {
    #[cfg(target_os = "windows")]
    { return 1; }
    #[cfg(target_os = "linux")]
    { return 2; }
    #[cfg(target_os = "macos")]
    { return 3; }
    #[allow(unreachable_code)]
    0
}

#[no_mangle]
pub extern "C" fn aether_graph_arch_id() -> u32 {
    #[cfg(target_arch = "x86_64")]
    { return 1; }
    #[cfg(target_arch = "aarch64")]
    { return 2; }
    #[cfg(target_arch = "x86")]
    { return 3; }
    #[cfg(target_arch = "arm")]
    { return 4; }
    #[cfg(target_arch = "riscv64")]
    { return 5; }
    #[allow(unreachable_code)]
    0
}

#[no_mangle]
pub extern "C" fn aether_graph_new(n: usize) -> *mut Graph {
    match catch_unwind(AssertUnwindSafe(|| Graph::new(n))) {
        Ok(Ok(graph)) => Box::into_raw(Box::new(graph)),
        Ok(Err(_)) | Err(_) => std::ptr::null_mut(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_free(ptr: *mut Graph) {
    if ptr.is_null() {
        return;
    }
    // A handle must be freed once and only once. The Python wrapper enforces this.
    let _ = catch_unwind(AssertUnwindSafe(|| unsafe { drop(Box::from_raw(ptr)) }));
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_add_edges(
    ptr: *mut Graph,
    data: *const u32,
    length: usize,
) -> i64 {
    ffi_i64(|| unsafe {
        let graph = graph_mut(ptr)?;
        if length % 2 != 0 {
            return Err(ERR_INVALID);
        }
        let values = input_u32_slice(data, length)?;
        graph.add_many(values)
    })
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_remove_edges(
    ptr: *mut Graph,
    data: *const u32,
    length: usize,
) -> i64 {
    ffi_i64(|| unsafe {
        let graph = graph_mut(ptr)?;
        if length % 2 != 0 {
            return Err(ERR_INVALID);
        }
        let values = input_u32_slice(data, length)?;
        graph.remove_many(values)
    })
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_reachable_many(
    ptr: *mut Graph,
    pairs: *const u32,
    output: *mut u8,
    query_count: usize,
) -> i64 {
    ffi_i64(|| unsafe {
        let graph = graph_mut(ptr)?;
        let input_len = query_count.checked_mul(2).ok_or(ERR_OVERFLOW)?;
        if input_len > (isize::MAX as usize) / size_of::<u32>() {
            return Err(ERR_OVERFLOW);
        }
        let values = input_u32_slice(pairs, input_len)?;
        for pair in values.chunks_exact(2) {
            if !graph.valid_node(pair[0]) || !graph.valid_node(pair[1]) {
                return Err(ERR_INVALID);
            }
        }
        let results = output_u8_slice(output, query_count)?;
        for (index, pair) in values.chunks_exact(2).enumerate() {
            results[index] = graph.reachable(pair[0], pair[1])? as u8;
        }
        i64::try_from(query_count).map_err(|_| ERR_OVERFLOW)
    })
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_add_edge(ptr: *mut Graph, u: u32, v: u32) -> i64 {
    ffi_i64(|| unsafe { Ok(graph_mut(ptr)?.add(u, v)? as i64) })
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_remove_edge(ptr: *mut Graph, u: u32, v: u32) -> i64 {
    ffi_i64(|| unsafe { Ok(graph_mut(ptr)?.remove(u, v)? as i64) })
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_has_edge(ptr: *mut Graph, u: u32, v: u32) -> i64 {
    ffi_i64(|| unsafe {
        let graph = graph_ref(ptr as *const Graph)?;
        if !graph.valid_node(u) || !graph.valid_node(v) {
            return Err(ERR_INVALID);
        }
        Ok(graph.rows[u as usize].contains(&v) as i64)
    })
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_reachable(ptr: *mut Graph, source: u32, target: u32) -> i64 {
    ffi_i64(|| unsafe { Ok(graph_mut(ptr)?.reachable(source, target)? as i64) })
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_edge_count(ptr: *const Graph) -> i64 {
    ffi_i64(|| unsafe {
        let graph = graph_ref(ptr)?;
        i64::try_from(graph.edges).map_err(|_| ERR_OVERFLOW)
    })
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_memory_bytes(ptr: *const Graph) -> i64 {
    ffi_i64(|| unsafe {
        let graph = graph_ref(ptr)?;
        let bytes = graph.memory_bytes().ok_or(ERR_OVERFLOW)?;
        i64::try_from(bytes).map_err(|_| ERR_OVERFLOW)
    })
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_neighbor_count(ptr: *const Graph, node: u32) -> i64 {
    ffi_i64(|| unsafe {
        let graph = graph_ref(ptr)?;
        if !graph.valid_node(node) {
            return Err(ERR_INVALID);
        }
        i64::try_from(graph.rows[node as usize].len()).map_err(|_| ERR_OVERFLOW)
    })
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_copy_neighbors(
    ptr: *const Graph,
    node: u32,
    output: *mut u32,
    capacity: usize,
) -> i64 {
    ffi_i64(|| unsafe {
        let graph = graph_ref(ptr)?;
        if !graph.valid_node(node) {
            return Err(ERR_INVALID);
        }
        let row = &graph.rows[node as usize];
        if capacity < row.len() {
            return Err(ERR_BUFFER_TOO_SMALL);
        }
        let buffer = output_u32_slice(output, row.len())?;
        buffer.copy_from_slice(row);
        i64::try_from(row.len()).map_err(|_| ERR_OVERFLOW)
    })
}

unsafe fn output_u32_slice<'a>(data: *mut u32, length: usize) -> Result<&'a mut [u32], i64> {
    if length > (isize::MAX as usize) / size_of::<u32>() {
        return Err(ERR_OVERFLOW);
    }
    if length == 0 {
        return Ok(&mut []);
    }
    if data.is_null() {
        return Err(ERR_NULL);
    }
    // The caller must provide a writable, aligned allocation of `length` u32s.
    Ok(unsafe { slice::from_raw_parts_mut(data, length) })
}
