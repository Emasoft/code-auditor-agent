/* fixture for database_engine — C-language storage engine stub.
 *
 * The database_engine fingerprint requires a .c file AND a .rs file
 * containing the magic strings wal_append, page_alloc, commit_record,
 * btree_split. This file supplies the .c half plus a representative
 * set of storage-engine APIs the discoverer enumerates.
 *
 * No CMakeLists.txt / Makefile is included on purpose — the library_c
 * fingerprint requires one of those as a primary_glob, and we want
 * database_engine to be the unambiguous primary detected type.
 */

#include <stddef.h>

struct page;
struct btree;
struct tx;

/* page_alloc — storage layer page allocator (library_export, page). */
struct page *page_alloc(unsigned int size)
{
    (void)size;
    return NULL;
}

/* page_release — storage layer page deallocator (library_export, page). */
void page_release(struct page *p)
{
    (void)p;
}

/* btree_insert — B-tree insertion (library_export, btree). */
int btree_insert(struct btree *bt, const void *key, const void *val)
{
    (void)bt;
    (void)key;
    (void)val;
    return 0;
}

/* btree_split — B-tree node split on overflow (library_export, btree). */
int btree_split(struct btree *bt, struct page *p)
{
    (void)bt;
    (void)p;
    return 0;
}

/* wal_append — WAL record append (library_export, wal). */
int wal_append(const void *record, unsigned int len)
{
    (void)record;
    (void)len;
    return 0;
}

/* commit_record — group commit (library_export, storage). */
int commit_record(struct tx *t)
{
    (void)t;
    return 0;
}

/* query_execute — query layer entry point (db_query_handler, query). */
int query_execute(const char *sql)
{
    (void)sql;
    return 0;
}

/* tx_begin — start a transaction (db_query_handler, transaction). */
int tx_begin(struct tx **t)
{
    (void)t;
    return 0;
}
