// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";

const markup = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "index.html"), "utf8");
const BODY = markup.slice(markup.indexOf("<body>") + 6, markup.indexOf("</body>"));
const json = (data, status=200) => ({ ok: status < 400, status, json: async () => data });

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it.each([false, true])("V1 direct upload omits storage cookies and preserves identity (replay=%s)", async (replay) => {
  document.body.innerHTML = BODY;
  vi.resetModules();
  vi.useFakeTimers();
  vi.stubGlobal("FLICKPOND_LEGACY_API", false);
  vi.stubGlobal("crypto", webcrypto);
  const calls=[];
  const fetch = vi.fn(async (url, init) => {
    calls.push([url, init]);
    if (url.endsWith("auth/me")) return json({ id: "owner", email: "owner@example.test", role: "user" });
    if (url.endsWith("/uploads/reservations")) return json({
      reservation_id: "reserved", asset_id: "public-asset",
      upload: replay ? null : { url: "https://storage.test/bucket", fields: { key: "server-key", policy: "signed" } },
    },201);
    if (url.startsWith("https://storage.test")) return json({},204);
    if (url.endsWith("/finalize")) return json({ job_id: "public-asset" },202);
    return json({ id: "public-asset", filename: "clip.mp4", status: "queued" });
  });
  vi.stubGlobal("fetch", fetch);
  await import("./app.js");
  await vi.advanceTimersByTimeAsync(0);
  const file = new File(["video-bytes"], "clip.mp4", { type: "video/mp4" });
  file.arrayBuffer = async () => new TextEncoder().encode("video-bytes").buffer;
  const input=document.getElementById("file-input");
  Object.defineProperty(input,"files",{ value: [file], configurable: true });
  input.dispatchEvent(new Event("change"));
  // Native WebCrypto resolves outside the fake clock.
  await vi.waitFor(() => expect(calls.some(([url]) => url.endsWith("/finalize"))).toBe(true));
  const reserve = calls.find(([url]) => url.endsWith("/uploads/reservations"));
  const body=JSON.parse(reserve[1].body);
  expect(body).toMatchObject({ filename:"clip.mp4", size_bytes:11, content_type:"video/mp4" });
  expect(body.sha256).toMatch(/^[a-f0-9]{64}$/);
  const finalize = calls.find(([url]) => url.endsWith("/finalize"));
  expect(JSON.parse(finalize[1].body).request_id).toBe(body.request_id);
  const storage=calls.find(([url]) => url.startsWith("https://storage.test"));
  if (replay) expect(storage).toBeUndefined();
  else {
    expect(storage[1]).toMatchObject({ method:"POST", credentials:"omit", redirect:"error", mode:"cors" });
    expect(storage[1].headers).toBeUndefined();
    expect(storage[1].body.get("key")).toBe("server-key");
    expect(storage[1].body.get("file").name).toBe("clip.mp4");
  }
  expect(calls.some(([url]) => url === "/api/media/upload")).toBe(false);
});
