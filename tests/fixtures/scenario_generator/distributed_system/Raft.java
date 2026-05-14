// fixture for distributed_system — Java-language Raft handler stub.
//
// Required so the distributed_system fingerprint, which requires
// the strings appendEntries AND requestVote in a .java file, can fire.

package raft;

public class Raft {

    private long term;
    private int leader;

    // appendEntries — Raft RPC handler for log replication.
    // Maps to IPC_HANDLER (rpc) in the discoverer.
    public AppendEntriesReply appendEntries(AppendEntriesArgs args) {
        return new AppendEntriesReply(this.term);
    }

    // requestVote — Raft RPC handler for leader election.
    public RequestVoteReply requestVote(RequestVoteArgs args) {
        return new RequestVoteReply(false);
    }

    // installSnapshot — Raft RPC handler for log truncation.
    public InstallSnapshotReply installSnapshot(InstallSnapshotArgs args) {
        return new InstallSnapshotReply();
    }

    // becomeLeader — state transition: candidate -> leader.
    public void becomeLeader() {
        this.leader = 0;
    }

    // startElection — state transition: follower -> candidate.
    public void startElection() {
        this.term++;
    }
}
