// fixture for distributed_system — Rust-language Raft handler stub.
//
// Required so the distributed_system fingerprint, which requires
// matching strings to appear in BOTH a .go file AND a .rs file AND a
// .java file (appendEntries / request_vote / propose_value), can fire.
//
// No Cargo.toml is bundled — that would trip library_rust ([lib])
// or cli_rust ([[bin]]) and we want distributed_system to be the
// unambiguous primary detected type.

/// Raft consensus node state.
pub struct Raft {
    term: u64,
    leader: i32,
}

impl Raft {
    /// append_entries — Raft RPC handler for log replication.
    /// Maps to IPC_HANDLER (rpc) in the discoverer.
    pub fn append_entries(&mut self, args: &AppendEntriesArgs) -> AppendEntriesReply {
        let _ = args;
        AppendEntriesReply { term: self.term }
    }

    /// request_vote — Raft RPC handler for leader election.
    pub fn request_vote(&mut self, args: &RequestVoteArgs) -> RequestVoteReply {
        let _ = args;
        RequestVoteReply { granted: false }
    }

    /// install_snapshot — Raft RPC handler for log truncation.
    pub fn install_snapshot(&mut self, args: &InstallSnapshotArgs) -> InstallSnapshotReply {
        let _ = args;
        InstallSnapshotReply {}
    }

    /// propose_value — client API for committing a new entry.
    pub fn propose_value(&mut self, value: &[u8]) -> bool {
        let _ = value;
        true
    }

    /// become_leader — state transition: candidate -> leader.
    pub fn become_leader(&mut self) {
        self.leader = 0;
    }

    /// start_election — state transition: follower -> candidate.
    pub fn start_election(&mut self) {
        self.term += 1;
    }
}

// String alias so the fingerprint's `appendEntries` magic string also
// appears in this file alongside the snake_case form. The Rust regex
// will pick up the `fn` form above; this comment carries the camelCase
// for fingerprint detection only.
//
// appendEntries (camelCase reference; not callable)

/// AppendEntriesArgs / AppendEntriesReply / RequestVoteArgs / etc.
pub struct AppendEntriesArgs;
pub struct AppendEntriesReply {
    pub term: u64,
}
pub struct RequestVoteArgs;
pub struct RequestVoteReply {
    pub granted: bool,
}
pub struct InstallSnapshotArgs;
pub struct InstallSnapshotReply;
