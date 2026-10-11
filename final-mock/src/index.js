import OPENAPI from "../openapi.json";

const reply = (body, status = 200) => new Response(JSON.stringify(body), {
  status,
  headers: { "content-type": "application/json; charset=utf-8" },
});

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/health") return reply({ ok: true });
    if (request.method === "GET" && url.pathname === "/openapi.json") return reply(OPENAPI);
    return reply({ error: "final service contract is not implemented yet" }, 501);
  },
};
