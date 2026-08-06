use std::sync::atomic::{AtomicU64, Ordering};

use pyo3::prelude::*;
use smallvec::SmallVec;

pub(crate) enum Callback {
    Strong(Py<PyAny>),
    Weak(Py<PyAny>),
}

pub(crate) struct CallbackEntry {
    pub(crate) id: u64,
    pub(crate) priority: i32,
    pub(crate) callback: Callback,
    pub(crate) remaining: Option<AtomicU64>,
}

pub(crate) fn insert_sorted(callbacks: &mut SmallVec<[CallbackEntry; 4]>, entry: CallbackEntry) {
    let pos = callbacks.partition_point(|e| e.priority >= entry.priority);
    callbacks.insert(pos, entry);
}

pub(crate) enum PendingCallback {
    Resolved(Py<PyAny>),
    Weak(u64, Py<PyAny>),
}

pub(crate) fn saturating_dec(remaining: &AtomicU64) -> Option<bool> {
    let mut current = remaining.load(Ordering::Relaxed);
    loop {
        if current == 0 {
            return None;
        }
        let new = current - 1;
        match remaining.compare_exchange_weak(current, new, Ordering::Relaxed, Ordering::Relaxed) {
            Ok(_) => return Some(new == 0),
            Err(observed) => current = observed,
        }
    }
}