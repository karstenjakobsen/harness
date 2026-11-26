// Stdio MCP adapter running in the allocation. Only this process supplies file bytes.
import {
  constants as flags,
  openSync,
  fstatSync,
  readSync,
  writeFileSync,
  ftruncateSync,
  closeSync,
  readFileSync,
} from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";

const MAX_TEXT_FILE_BYTES = 16384;
const scratch = process.argv[2];
const endpoint = process.env.HARNESS_WORKER_MCP_URL;
const token = readFileSync(process.env.HARNESS_WORKER_IDENTITY_FILE ?? "/secrets/harness.jwt", "utf8").trim();
const filenameSchema = { type: "string", pattern: "^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$" };

function filePath(filename) {
  if (typeof filename !== "string" || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(filename) || /\s/.test(filename)) {
    throw new Error("Supply a plain filename of up to 128 ASCII characters.");
  }
  return join(scratch, filename);
}

function loadFile(filename) {
  const fd = openSync(filePath(filename), flags.O_RDONLY | flags.O_NOFOLLOW | flags.O_NONBLOCK);
  try {
    if (!fstatSync(fd).isFile()) throw new Error("Expected a regular scratch file.");
    const buffer = Buffer.alloc(MAX_TEXT_FILE_BYTES + 1);
    let size = 0;
    while (size < buffer.length) {
      const count = readSync(fd, buffer, size, buffer.length - size);
      if (!count) break;
      size += count;
    }
    if (size > MAX_TEXT_FILE_BYTES) throw new Error("File exceeds 16384 bytes.");
    const content = new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(
      buffer.subarray(0, size),
    );
    return { filename, content };
  } finally {
    closeSync(fd);
  }
}

function fileTool(name, description, properties) {
  return {
    name,
    description,
    inputSchema: {
      type: "object",
      properties,
      required: Object.keys(properties),
      additionalProperties: false,
    },
  };
}

async function handle(message) {
  const { id, method, params } = message;
  if (method === "tools/call") {
    const args = params.arguments ?? {};
    if (params.name === "write_text_file") {
      if (Object.keys(args).length !== 2 || !Object.hasOwn(args, "filename") || typeof args.content !== "string" ||
          !args.content.isWellFormed() || Buffer.byteLength(args.content) > MAX_TEXT_FILE_BYTES) {
        throw new Error("Supply a filename and at most 16384 UTF-8 bytes.");
      }
      const fd = openSync(
        filePath(args.filename),
        flags.O_WRONLY | flags.O_CREAT | flags.O_NOFOLLOW | flags.O_NONBLOCK,
        0o600,
      );
      try {
        if (!fstatSync(fd).isFile()) throw new Error("Expected a regular scratch file.");
        ftruncateSync(fd, 0);
        writeFileSync(fd, args.content, {encoding: "utf8"});
      } finally {
        closeSync(fd);
      }
      return {jsonrpc: "2.0", id, result: {content: [{type: "text", text: "Saved in worker scratch."}]}};
    }
    if (params.name === "submit_work_result" && !Object.hasOwn(args, "fixture")) {
      if (Object.keys(args).length !== 1 || !Object.hasOwn(args, "filename")) {
        throw new Error("Supply only the existing scratch filename.");
      }
      params.arguments = {text_file: loadFile(args.filename)};
    }
  }
  const response = await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
      Authorization: "Bearer " + token,
    },
    body: JSON.stringify(message),
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) throw new Error("Worker MCP returned HTTP " + response.status);
  if (id === undefined) return;
  const reply = await response.json();
  if (method === "tools/list" && reply.result) {
    const tools = reply.result.tools;
    const index = tools.findIndex(t => t.name === "submit_work_result" && t.inputSchema.properties.text_file);
    if (index >= 0) {
      tools.splice(index, 1,
        fileTool("write_text_file", "Write UTF-8 content to a file in private scratch.", {filename: filenameSchema, content: {type: "string"}}),
        fileTool("submit_work_result", "Read the named scratch file and submit its exact contents.", {filename: filenameSchema}));
    }
  }
  return reply;
}

for await (const line of createInterface({input: process.stdin})) {
  let message;
  try {
    message = JSON.parse(line);
    const reply = await handle(message);
    if (reply) console.log(JSON.stringify(reply));
  } catch (error) {
    if (message?.id !== undefined) {
      console.log(JSON.stringify({
        jsonrpc: "2.0",
        id: message.id,
        error: { code: -32602, message: error.message },
      }));
    }
  }
}
