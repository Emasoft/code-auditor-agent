// Fixture Express application exercising the four registration forms
// the discoverer must handle in v1:
//   1. app.get('/path', handler)    — GET on an Express app instance.
//   2. app.post('/path', handler)   — POST with a JSDoc above it.
//   3. app.delete('/path', handler) — DELETE with a // comment above it.
//   4. router.get('/path', handler) — GET on an express.Router() instance.
const express = require('express');

const app = express();
const apiRouter = express.Router();

// List every widget currently in the inventory.
app.get('/widgets', (req, res) => {
  res.json({ widgets: [] });
});

/**
 * Create a new widget from the request body.
 * Returns the created widget with its server-assigned id.
 */
app.post('/widgets', (req, res) => {
  res.status(201).json({ id: 1, ...req.body });
});

// Remove the widget identified by :id; idempotent.
app.delete('/widgets/:id', (req, res) => {
  res.status(204).end();
});

apiRouter.get('/health', (req, res) => {
  res.json({ ok: true });
});

app.use('/api', apiRouter);

app.listen(3000);
