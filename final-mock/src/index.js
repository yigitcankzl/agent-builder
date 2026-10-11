import OPENAPI from "../openapi.json";
import TEST_DATA from "../data/test-customers.json";

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, POST, OPTIONS",
  "access-control-allow-headers": "*",
};
const reply = (body, status = 200) => Response.json(body, { status, headers: CORS });
const customers = new Map(TEST_DATA.customers.map((customer) => [String(customer.customerNo), customer]));
const isTemplate = (value) => typeof value === "string" &&
  (value.startsWith("{{") || value.startsWith("%7B%7B"));
const missing = (value) => value === undefined || value === null || value === "";

function result(code, message, type = "ERROR", rootCause = "ValidationError", status = 400) {
  const guid = "freya-final-mock";
  return reply({ result: {
    guid, returnCode: code, messageText: message, code, message, type,
    details: { guid, rootCause, errorOrigin: "freya-final-mock" },
  } }, status);
}

const invalid = (field) => result("INVALID_ARGUMENTS_ERROR", `${field} cannot be empty`);

function notFound(service) {
  const errors = {
    "cards.list": ["FB_IVR_CHANNEL_102", "Müşteriye ait geçerli kart bilgisi bulunamadı."],
    "cards.balance": ["FB_IVR_CHANNEL_120", "Kart bakiye servisi hatası: kart bulunamadı"],
    "statement.week.get": ["FB_IVR_CHANNEL_121", "Kart bulunamadı"],
    "statement.pdf.send": ["FB_IVR_CHANNEL_107", "Pdf dokümanı bulunamadı"],
  };
  const found = errors[service];
  return found
    ? result(found[0], found[1], "WARNING", "NotFoundException", 404)
    : result("INVALID_ARGUMENTS_ERROR", "requested record was not found");
}

function firstRecord(service) {
  for (const customer of TEST_DATA.customers) {
    const records = customer.services[service];
    if (!records) continue;
    if (records.http !== undefined) return records;
    for (const value of Object.values(records)) {
      if (value.http !== undefined) return value;
      const nested = Object.values(value)[0];
      if (nested) return nested;
    }
  }
  return null;
}

function findRecord(service, data) {
  if (isTemplate(data.customerNo) || isTemplate(data.cardNumber) || isTemplate(data.newStatementWeek)) {
    return firstRecord(service);
  }
  if (service === "cards.list" || service === "contact.email.get" || service === "statement.pdf.send") {
    return customers.get(String(data.customerNo))?.services?.[service] || null;
  }
  for (const customer of TEST_DATA.customers) {
    const byCard = customer.services[service];
    if (!byCard || !Object.hasOwn(byCard, String(data.cardNumber))) continue;
    const record = byCard[String(data.cardNumber)];
    return service === "statement.week.decide" || service === "statement.week.change"
      ? record[String(data.newStatementWeek)] || null
      : record;
  }
  return null;
}

const required = {
  "cards.list": ["customerNo"],
  "cards.balance": ["cardNumber"],
  "statement.week.get": ["cardNumber"],
  "statement.week.decide": ["cardNumber", "newStatementWeek", "statementDay"],
  "statement.week.change": ["cardNumber", "newStatementWeek", "statementDay"],
  "contact.email.get": ["customerNo", "intAddressInfoType"],
  "statement.pdf.send": ["customerNo", "cardNumber", "currencyType", "statementDate", "emailAddress"],
};

async function service(request, name) {
  let body;
  try { body = await request.json(); } catch { return invalid("request body"); }
  const data = body?.data || {};
  const absent = required[name].find((field) => missing(data[field]));
  if (absent) return invalid(absent);
  const record = findRecord(name, data);
  if (!record) return notFound(name);
  if (record.delaySeconds) await new Promise((resolve) => setTimeout(resolve, record.delaySeconds * 1000));
  return reply(record.response, record.http);
}

export default {
  async fetch(request) {
    const url = new URL(request.url);
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    if (request.method === "GET" && url.pathname === "/health") return reply({ durum: "ok" });
    if (request.method === "GET" && url.pathname === "/openapi.json") return reply(OPENAPI);
    const match = url.pathname.match(/^\/voice\/v1\/([^/]+)$/);
    if (request.method === "POST" && match && required[match[1]]) return service(request, match[1]);
    return reply({ hata: "bulunamadı" }, 404);
  },
};
