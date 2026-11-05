use std::mem::size_of;

pub struct Graph {
    rows: Vec<Vec<u32>>,
    marks: Vec<u32>,
    stack: Vec<u32>,
    epoch: u32,
    edges: usize,
}

impl Graph {
    fn new(n: usize) -> Option<Self> {
        if n == 0 || n > u32::MAX as usize { return None; }
        Some(Self {
            rows: (0..n).map(|_| Vec::new()).collect(),
            marks: vec![0; n],
            stack: Vec::new(),
            epoch: 0,
            edges: 0,
        })
    }

    fn add(&mut self, u: u32, v: u32) -> bool {
        let Some(row) = self.rows.get_mut(u as usize) else { return false; };
        if row.contains(&v) { return false; }
        row.push(v);
        self.edges += 1;
        true
    }

    fn remove(&mut self, u: u32, v: u32) -> bool {
        let Some(row) = self.rows.get_mut(u as usize) else { return false; };
        let Some(i) = row.iter().position(|&x| x == v) else { return false; };
        row.swap_remove(i);
        self.edges -= 1;
        true
    }

    fn reachable(&mut self, source: u32, target: u32) -> Option<bool> {
        if source as usize >= self.rows.len() || target as usize >= self.rows.len() { return None; }
        if source == target { return Some(true); }
        self.epoch = self.epoch.wrapping_add(1);
        if self.epoch == 0 {
            self.marks.fill(0);
            self.epoch = 1;
        }
        let epoch = self.epoch;
        self.stack.clear();
        self.stack.push(source);
        self.marks[source as usize] = epoch;
        while let Some(u) = self.stack.pop() {
            for &v in &self.rows[u as usize] {
                if v == target { return Some(true); }
                if self.marks[v as usize] != epoch {
                    self.marks[v as usize] = epoch;
                    self.stack.push(v);
                }
            }
        }
        Some(false)
    }

    fn memory_bytes(&self) -> usize {
        size_of::<Self>()
            + self.rows.capacity() * size_of::<Vec<u32>>()
            + self.rows.iter().map(|r| r.capacity() * size_of::<u32>()).sum::<usize>()
            + self.marks.capacity() * size_of::<u32>()
            + self.stack.capacity() * size_of::<u32>()
    }
}

#[no_mangle]
pub extern "C" fn aether_graph_new(n: usize) -> *mut Graph {
    match Graph::new(n) {
        Some(graph) => Box::into_raw(Box::new(graph)),
        None => std::ptr::null_mut(),
    }
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_free(ptr: *mut Graph) {
    if !ptr.is_null() { drop(Box::from_raw(ptr)); }
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_add_edges(ptr: *mut Graph, data: *const u32, length: usize) -> i64 {
    if ptr.is_null() || length % 2 != 0 || (length > 0 && data.is_null()) { return -1; }
    let graph = &mut *ptr;
    let values = if length == 0 { &[][..] } else { std::slice::from_raw_parts(data, length) };
    let mut changed = 0i64;
    for pair in values.chunks_exact(2) {
        if pair[0] as usize >= graph.rows.len() || pair[1] as usize >= graph.rows.len() { return -1; }
        if graph.add(pair[0], pair[1]) { changed += 1; }
    }
    changed
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_add_edge(ptr: *mut Graph, u: u32, v: u32) -> i32 {
    if ptr.is_null() { return -1; }
    let graph = &mut *ptr;
    if u as usize >= graph.rows.len() || v as usize >= graph.rows.len() { return -1; }
    graph.add(u, v) as i32
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_remove_edge(ptr: *mut Graph, u: u32, v: u32) -> i32 {
    if ptr.is_null() { return -1; }
    let graph = &mut *ptr;
    if u as usize >= graph.rows.len() || v as usize >= graph.rows.len() { return -1; }
    graph.remove(u, v) as i32
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_has_edge(ptr: *mut Graph, u: u32, v: u32) -> i32 {
    if ptr.is_null() { return -1; }
    let graph = &*ptr;
    if u as usize >= graph.rows.len() || v as usize >= graph.rows.len() { return -1; }
    graph.rows[u as usize].contains(&v) as i32
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_reachable(ptr: *mut Graph, source: u32, target: u32) -> i32 {
    if ptr.is_null() { return -1; }
    match (&mut *ptr).reachable(source, target) {
        Some(true) => 1,
        Some(false) => 0,
        None => -1,
    }
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_edge_count(ptr: *const Graph) -> usize {
    if ptr.is_null() { return 0; }
    (*ptr).edges
}

#[no_mangle]
pub unsafe extern "C" fn aether_graph_memory_bytes(ptr: *const Graph) -> usize {
    if ptr.is_null() { return 0; }
    (*ptr).memory_bytes()
}
