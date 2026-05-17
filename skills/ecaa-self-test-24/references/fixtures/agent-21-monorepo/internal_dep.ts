// Cross-package imports that bypass each sibling package's public API.
// Each `internal/` / `src/` path is a private boundary the new module
// is reaching across — monorepo reviewer must flag every line.
import { secretHelper } from "@org/auth/internal/secrets";
import { dbInternal } from "@org/db/src/internals";
import { uiPrivate } from "@org/ui/internal/private";

export function leak() {
  return { secretHelper, dbInternal, uiPrivate };
}
