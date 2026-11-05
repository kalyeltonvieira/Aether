use std::io::{self, Read};
use std::time::Instant;

fn reachable_csr(
    offsets: &[usize],
    edges: &[u32],
    source: u32,
    target: u32,
    marks: &mut [u32],
    epoch: u32,
    stack: &mut Vec<u32>,
) -> bool {
    if source == target { return true; }
    stack.clear();
    stack.push(source);
    marks[source as usize] = epoch;
    while let Some(u) = stack.pop() {
        let u = u as usize;
        for &v in &edges[offsets[u]..offsets[u + 1]] {
            if v == target { return true; }
            let vi = v as usize;
            if marks[vi] != epoch {
                marks[vi] = epoch;
                stack.push(v);
            }
        }
    }
    false
}

fn next<T: std::str::FromStr>(it: &mut std::str::SplitAsciiWhitespace<'_>) -> T
where <T as std::str::FromStr>::Err: std::fmt::Debug {
    it.next().expect("missing input token").parse().expect("invalid input token")
}

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).expect("read stdin");
    let mut it = input.split_ascii_whitespace();
    let n: usize = next(&mut it);
    let m: usize = next(&mut it);
    let q: usize = next(&mut it);
    let repetitions: usize = next(&mut it);
    let mut rows: Vec<Vec<u32>> = (0..n).map(|_| Vec::new()).collect();
    for _ in 0..m {
        let u: usize = next(&mut it);
        let v: u32 = next(&mut it);
        rows[u].push(v);
    }
    let mut queries = Vec::with_capacity(q);
    for _ in 0..q {
        queries.push((next::<u32>(&mut it), next::<u32>(&mut it)));
    }
    let mut offsets = Vec::with_capacity(n + 1);
    let mut edges = Vec::with_capacity(m);
    offsets.push(0);
    for row in rows {
        edges.extend(row);
        offsets.push(edges.len());
    }
    let mut marks = vec![0u32; n];
    let mut stack = Vec::new();
    let mut epoch: u32 = 1;
    let start = Instant::now();
    let mut positive = 0usize;
    let mut answer_bits = Vec::with_capacity(q * repetitions);
    for _ in 0..repetitions {
        for &(s, t) in &queries {
            let result = reachable_csr(&offsets, &edges, s, t, &mut marks, epoch, &mut stack);
            positive += result as usize;
            answer_bits.push(if result { '1' } else { '0' });
            epoch = epoch.wrapping_add(1);
            if epoch == 0 { marks.fill(0); epoch = 1; }
        }
    }
    let elapsed_ns = start.elapsed().as_nanos();
    println!("{} {} {} {}", q * repetitions, positive, elapsed_ns, answer_bits.iter().collect::<String>());
}
