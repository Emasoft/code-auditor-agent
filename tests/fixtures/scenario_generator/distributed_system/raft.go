// fixture for distributed_system — Go-language Raft handler stub.
//
// The distributed_system fingerprint requires the magic strings
// appendEntries, requestVote, proposeValue to appear in a .go file
// (plus matching strings in a .rs and a .java file — see raft.rs and
// Raft.java). The handlers below are picked up by the
// distributed_system discoverer as IPC_HANDLER entries.
//
// Lives in package "raft" — NOT "main" — so the cli_go fingerprint
// (which requires `package main` in main.go) does not also match.

package raft

// Raft is the per-node consensus state.
type Raft struct {
	term     uint64
	votedFor int
	leader   int
}

// AppendEntries is the Raft RPC handler for log replication.
// Maps to IPC_HANDLER (rpc).
func (r *Raft) AppendEntries(args *AEArgs, reply *AEReply) error {
	_ = args
	_ = reply
	return nil
}

// RequestVote is the Raft RPC handler for leader election.
// Maps to IPC_HANDLER (rpc).
func (r *Raft) RequestVote(args *RVArgs, reply *RVReply) error {
	_ = args
	_ = reply
	return nil
}

// InstallSnapshot is the Raft RPC handler for log truncation.
// Maps to IPC_HANDLER (rpc).
func (r *Raft) InstallSnapshot(args *ISArgs, reply *ISReply) error {
	_ = args
	_ = reply
	return nil
}

// ProposeValue is the client-facing API for committing a new value.
// In Raft this routes through the leader's AppendEntries broadcast.
// Maps to IPC_HANDLER (rpc).
func (r *Raft) ProposeValue(value []byte) error {
	_ = value
	return nil
}

// BecomeLeader transitions the node from candidate to leader.
// Maps to IPC_HANDLER (state_transition).
func (r *Raft) BecomeLeader() {
	r.leader = 0
}

// StartElection bumps the term and broadcasts RequestVote.
// Maps to IPC_HANDLER (state_transition).
func (r *Raft) StartElection() {
	r.term++
}

// appendEntries (lowercase) — same handler under the unexported name.
// Present so the fingerprint's string match (`appendEntries`) is direct.
func (r *Raft) appendEntries(args *AEArgs) error {
	_ = args
	return nil
}

// requestVote (lowercase) — same handler under the unexported name.
// Present so the fingerprint's string match (`requestVote`) is direct.
func (r *Raft) requestVote(args *RVArgs) error {
	_ = args
	return nil
}

// proposeValue (lowercase) — internal alias.
// Present so the fingerprint's string match (`proposeValue`) is direct.
func (r *Raft) proposeValue(value []byte) error {
	_ = value
	return nil
}

// AEArgs / AEReply / RVArgs / RVReply / ISArgs / ISReply are wire types.
type AEArgs struct{}
type AEReply struct{}
type RVArgs struct{}
type RVReply struct{}
type ISArgs struct{}
type ISReply struct{}
