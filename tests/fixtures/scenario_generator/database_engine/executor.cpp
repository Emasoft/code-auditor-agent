// fixture for database_engine — C++ query executor stub.
//
// Adds DB_QUERY_HANDLER coverage from C++ for the discoverer. The
// database_engine fingerprint does not require C++ content; this is
// here to give the goldens non-trivial cpp coverage so refactors
// to the cpp regex are tested.

#include <string>

namespace db {

// query_prepare — prepare a SQL statement for execution.
int query_prepare(const std::string& sql) {
    (void)sql;
    return 0;
}

// query_execute — execute a prepared statement.
int query_execute(int handle) {
    (void)handle;
    return 0;
}

// tx_commit — finalise a transaction.
bool tx_commit(int tx_id) {
    (void)tx_id;
    return true;
}

}  // namespace db
