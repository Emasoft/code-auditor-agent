import { NextResponse } from "next/server";

type Order = { id: number; total: number };

const ORDERS: Order[] = [
  { id: 100, total: 4200 },
  { id: 101, total: 9900 },
];

export async function GET() {
  return NextResponse.json({ orders: ORDERS });
}

export async function POST(request: Request) {
  const body = (await request.json()) as { total?: number };
  if (typeof body?.total !== "number") {
    return NextResponse.json({ error: "total must be a number" }, { status: 400 });
  }
  const created: Order = { id: ORDERS.length + 100, total: body.total };
  ORDERS.push(created);
  return NextResponse.json(created, { status: 201 });
}
