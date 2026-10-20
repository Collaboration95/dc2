// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { webcrypto } from "node:crypto";
import { afterEach, expect, it, vi } from "vitest";

const markup = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "index.html"), "utf8");
const BODY = markup.slice(markup.indexOf("<body>") + 6, markup.indexOf("</body>"));
const json = (data, status=200) => ({ ok: status < 400, status, json: async () => data });
const STORAGE_URL = "https://storage.test/bucket";
const reservation = () => ({
  reservation_id: "reserved", asset_id: "public-asset",
  upload: { url: STORAGE_URL, fields: { key: "server-key", policy: "signed" } },
});

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

async function loadDirectApp(handler) {
  document.body.innerHTML = BODY;
  vi.resetModules();
  vi.useFakeTimers();
  vi.stubGlobal("FLICKPOND_LEGACY_API", false);
  vi.stubGlobal("crypto", webcrypto);
  const calls = [];
  const fetch = vi.fn(async (url, init) => {
    calls.push([url, init]);
    if (url.endsWith("/auth/me")) return json({ id: "owner", email: "owner@example.test", role: "user" });
    return handler(url, init);
  });
  vi.stubGlobal("fetch", fetch);
  await import("./app.js");
  await vi.advanceTimersByTimeAsync(0);
  return {
    calls,
    auth: document.getElementById("auth"),
    authEmail: document.getElementById("auth-email"),
    authPassword: document.getElementById("auth-password"),
    authForm: document.getElementById("auth-form"),
    who: document.getElementById("who"),
    logout: document.getElementById("logout"),
    fileInput: document.getElementById("file-input"),
    status: document.getElementById("status"),
    activeJob: document.getElementById("active-job"),
    jobFilename: document.getElementById("job-filename"),
    jobBadge: document.getElementById("job-badge"),
    jobActions: document.getElementById("job-actions"),
  };
}

function directFile(name = "clip.mp4") {
  const file = new File(["video-bytes"], name, { type: "video/mp4" });
  file.arrayBuffer = async () => new TextEncoder().encode("video-bytes").buffer;
  return file;
}

function selectFile(page, file = directFile()) {
  Object.defineProperty(page.fileInput, "files", { value: [file], configurable: true });
  page.fileInput.dispatchEvent(new Event("change"));
  return file;
}

function signIn(page, id) {
  page.authEmail.value = `${id}@example.test`;
  page.authPassword.value = "fixture-password";
  page.authForm.dispatchEvent(new Event("submit", { cancelable: true }));
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

it("stops after a refused storage upload and offers a retry without finalizing", async () => {
  const page = await loadDirectApp((url) => {
    if (url.endsWith("/uploads/reservations")) return json(reservation(), 201);
    if (url === STORAGE_URL) return json({ error: "private storage trace", bucket: "private-bucket" }, 403);
    throw new Error(`Unexpected request: ${url}`);
  });
  selectFile(page);

  await vi.waitFor(() => expect(page.status.textContent).toContain("Storage upload failed"));

  expect(page.status.textContent).toContain("Retry to replay this upload.");
  expect(page.status.textContent).not.toContain("private storage trace");
  expect(page.status.textContent).not.toContain("private-bucket");
  expect(page.activeJob.hidden).toBe(false);
  expect(page.jobActions.hidden).toBe(false);
  expect(page.calls.filter(([url]) => url.endsWith("/finalize"))).toHaveLength(0);
  expect(page.calls.some(([url]) => url.includes("/jobs/public-asset"))).toBe(false);
});

it.each([
  { status: 409, error: "upload is incomplete; retry finalization", attempts: 1 },
  { status: 410, error: "upload reservation expired", attempts: 1 },
  { status: 503, error: "source object unavailable; retry finalization", attempts: 2, retryVisible: true },
])("shows a safe finalize $status outcome", async ({ status, error, attempts, retryVisible }) => {
  const page = await loadDirectApp((url) => {
    if (url.endsWith("/uploads/reservations")) return json(reservation(), 201);
    if (url === STORAGE_URL) return json({}, 204);
    if (url.endsWith("/finalize")) {
      return json({ error, debug: "private-bucket/server-key" }, status);
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  selectFile(page);

  await vi.waitFor(() => expect(page.calls.filter(([url]) => url.endsWith("/finalize"))).toHaveLength(attempts));
  await vi.waitFor(() => expect(page.status.textContent).toContain(`Upload failed: ${error}`));

  expect(page.status.textContent).not.toContain("private-bucket");
  expect(page.status.textContent).not.toContain("server-key");
  expect(page.activeJob.hidden).toBe(false);
  if (retryVisible) expect(page.jobActions.hidden).toBe(false);
  expect(page.calls.some(([url]) => url.includes("/jobs/public-asset"))).toBe(false);
});

it("reuses the reservation and finalize idempotency keys after lost replies", async () => {
  let reservationAttempts = 0;
  let finalizeAttempts = 0;
  const page = await loadDirectApp((url) => {
    if (url.endsWith("/uploads/reservations")) {
      reservationAttempts += 1;
      return reservationAttempts === 1
        ? Promise.reject(new Error("reservation reply lost"))
        : json(reservation(), 201);
    }
    if (url === STORAGE_URL) return json({}, 204);
    if (url.endsWith("/finalize")) {
      finalizeAttempts += 1;
      return finalizeAttempts === 1
        ? Promise.reject(new Error("finalize reply lost"))
        : json({ job_id: "public-asset" }, 202);
    }
    if (url.endsWith("/jobs/public-asset")) {
      return json({ id: "public-asset", filename: "clip.mp4", status: "queued", submission_status: "pending" });
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  selectFile(page);

  await vi.waitFor(() => expect(page.calls.filter(([url]) => url.endsWith("/finalize"))).toHaveLength(2));
  await vi.waitFor(() => expect(page.activeJob.hidden).toBe(false));

  const reservations = page.calls.filter(([url]) => url.endsWith("/uploads/reservations"));
  const finalizations = page.calls.filter(([url]) => url.endsWith("/finalize"));
  const reservationBodies = reservations.map(([, init]) => JSON.parse(init.body));
  const finalizeBodies = finalizations.map(([, init]) => JSON.parse(init.body));
  expect(reservationBodies).toHaveLength(2);
  expect(reservationBodies[0].request_id).toBe(reservationBodies[1].request_id);
  expect(reservations[0][1].headers["Idempotency-Key"]).toBe(reservations[1][1].headers["Idempotency-Key"]);
  expect(finalizeBodies).toEqual([{ request_id: reservationBodies[0].request_id }, { request_id: reservationBodies[0].request_id }]);
  expect(finalizations[0][1].headers["Idempotency-Key"]).toBe(finalizations[1][1].headers["Idempotency-Key"]);
  expect(page.calls.filter(([url]) => url === STORAGE_URL)).toHaveLength(1);
  expect(page.jobFilename.textContent).toBe("clip.mp4");
  expect(page.jobBadge.textContent).toBe("Queued");
});

it("does not finalize owner A's delayed storage upload after owner B signs in", async () => {
  const storageReply = deferred();
  const page = await loadDirectApp((url) => {
    if (url.endsWith("/uploads/reservations")) return json(reservation(), 201);
    if (url === STORAGE_URL) return storageReply.promise;
    if (url.endsWith("/auth/logout")) return json({}, 204);
    if (url.endsWith("/auth/login")) return json({ id: "owner-b", email: "owner-b@example.test", role: "user" });
    throw new Error(`Unexpected request: ${url}`);
  });
  selectFile(page, directFile("owner-a.mp4"));
  await vi.waitFor(() => expect(page.calls.some(([url]) => url === STORAGE_URL)).toBe(true));

  page.logout.click();
  await vi.waitFor(() => expect(page.auth.hidden).toBe(false));
  signIn(page, "owner-b");
  await vi.waitFor(() => expect(page.who.textContent).toBe("owner-b@example.test"));
  storageReply.resolve(json({}, 204));
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(0);

  expect(page.auth.hidden).toBe(true);
  expect(page.activeJob.hidden).toBe(true);
  expect(page.calls.filter(([url]) => url.endsWith("/finalize"))).toHaveLength(0);
});

it("ignores owner A's delayed finalize acceptance after owner B signs in", async () => {
  const finalizeReply = deferred();
  const page = await loadDirectApp((url) => {
    if (url.endsWith("/uploads/reservations")) return json(reservation(), 201);
    if (url === STORAGE_URL) return json({}, 204);
    if (url.endsWith("/finalize")) return finalizeReply.promise;
    if (url.endsWith("/auth/logout")) return json({}, 204);
    if (url.endsWith("/auth/login")) return json({ id: "owner-b", email: "owner-b@example.test", role: "user" });
    throw new Error(`Unexpected request: ${url}`);
  });
  selectFile(page, directFile("owner-a.mp4"));
  await vi.waitFor(() => expect(page.calls.some(([url]) => url.endsWith("/finalize"))).toBe(true));

  page.logout.click();
  await vi.waitFor(() => expect(page.auth.hidden).toBe(false));
  signIn(page, "owner-b");
  await vi.waitFor(() => expect(page.who.textContent).toBe("owner-b@example.test"));
  finalizeReply.resolve(json({ job_id: "owner-a-asset" }, 202));
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(0);

  expect(page.auth.hidden).toBe(true);
  expect(page.activeJob.hidden).toBe(true);
  expect(page.jobFilename.textContent).not.toBe("owner-a.mp4");
  expect(page.calls.some(([url]) => url.endsWith("/jobs/owner-a-asset"))).toBe(false);
});

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
