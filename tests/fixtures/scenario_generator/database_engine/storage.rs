// fixture for database_engine — Rust-language storage engine stub.
//
// Required so the database_engine fingerprint (which requires a .c
// AND a .rs file containing wal_append, page_alloc, commit_record,
// btree_split) can match. No Cargo.toml is bundled — that would
// trip the library_rust ([lib]) or cli_rust ([[bin]]) fingerprints
// and we want database_engine to be the unambiguous primary type.

/// page_alloc — storage layer page allocator (library_export, page).
pub fn page_alloc(size: usize) -> *mut u8 {
    let _ = size;
    std::ptr::null_mut()
}

/// page_release — storage layer page deallocator (library_export, page).
pub fn page_release(p: *mut u8) {
    let _ = p;
}

/// btree_split — B-tree node split (library_export, btree).
pub fn btree_split(node: *mut u8) -> bool {
    let _ = node;
    true
}

/// btree_insert — B-tree insertion (library_export, btree).
pub fn btree_insert(node: *mut u8, key: &[u8]) -> bool {
    let _ = node;
    let _ = key;
    true
}

/// wal_append — WAL append (library_export, wal).
pub fn wal_append(record: &[u8]) -> usize {
    record.len()
}

/// wal_replay — WAL recovery replay (library_export, wal).
pub fn wal_replay(start: u64) -> u64 {
    start
}

/// commit_record — write a commit marker (library_export, storage).
pub fn commit_record(lsn: u64) -> bool {
    let _ = lsn;
    true
}

/// mvcc_begin — start a snapshot read (db_query_handler, transaction).
pub fn mvcc_begin() -> u64 {
    0
}

/// mvcc_commit — finalise a snapshot transaction (db_query_handler, transaction).
pub fn mvcc_commit(tx_id: u64) -> bool {
    let _ = tx_id;
    true
}
