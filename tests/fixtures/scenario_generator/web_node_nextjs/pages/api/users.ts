import type { NextApiRequest, NextApiResponse } from "next";

type User = { id: number; name: string };

const USERS: User[] = [
  { id: 1, name: "Alice" },
  { id: 2, name: "Bob" },
];

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method === "GET") {
    res.status(200).json({ users: USERS });
    return;
  }
  if (req.method === "POST") {
    const body = req.body as { name?: string };
    if (!body?.name) {
      res.status(400).json({ error: "name is required" });
      return;
    }
    const created: User = { id: USERS.length + 1, name: body.name };
    USERS.push(created);
    res.status(201).json(created);
    return;
  }
  res.setHeader("Allow", "GET, POST");
  res.status(405).end();
}
