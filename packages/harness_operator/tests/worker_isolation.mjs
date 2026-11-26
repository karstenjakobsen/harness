// Executed inside the controlled real worker. Emit only route names and outcomes.
import http from "node:http";
import assert from "node:assert/strict";
import {randomUUID} from "node:crypto";
import {readFileSync} from "node:fs";
const [nomadPort, ownerPort, goal] = process.argv.slice(2);
const token = readFileSync("/secrets/harness.jwt", "utf8").trim();
const endpoint = process.env.HARNESS_WORKER_MCP_URL;
const bridge = new URL(endpoint).hostname;

function status(options) {
  return new Promise(resolve => {
    const req = http.get({...options, timeout: 1800}, res => {res.resume(); resolve(res.statusCode)});
    req.on("timeout", () => req.destroy());
    req.on("error", () => resolve("unreachable"));
  });
}
for (const [route, options] of Object.entries({
  task_socket: {socketPath:"/secrets/api.sock"},
  host_gateway: {host:"host.docker.internal", port:nomadPort},
  worker_service_host: {host:bridge, port:nomadPort},
})) {
  for (const [kind, credential] of [["missing", null], ["invalid",randomUUID()], ["worker",token]]) {
    const observed = await status({...options, path:"/v1/jobs", headers:credential ? {"X-Nomad-Token":credential} : {}});
    console.log(route, kind, observed);
    assert.ok([401,403,"unreachable"].includes(observed), `management route ${route}, ${kind}: ${observed}`);
  }
}
for (const host of new Set(["host.docker.internal", bridge, "127.0.0.1"])) {
  for (const [kind, headers] of [["missing", {}], ["worker", {Authorization: "Bearer " + token}]]) {
    const observed = await status({host, port:ownerPort, path:"/goals/"+goal, headers});
    console.log("owner HTTP", host, kind, observed);
    assert.ok([401,403,"unreachable"].includes(observed), `owner HTTP ${host} ${kind}: ${observed}`);
  }
}
async function rpc(name, args) {
  const reply = await fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json",
    Accept:"application/json, text/event-stream", Authorization:"Bearer "+token},
    body:JSON.stringify({jsonrpc:"2.0", id:1, method:"tools/call", params:{name,arguments:args}})});
  assert.equal(reply.status,200);
  const body = await reply.json();
  assert.ok(body.result && !body.result.isError);
}
await rpc("get_work_brief", {});
await rpc("submit_work_result", {text_file:{filename:"probe.txt",content:"ready\n"}});
console.log("worker MCP brief and submission succeeded");
