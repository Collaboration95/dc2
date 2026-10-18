// @vitest-environment jsdom
//
// Tests for app.js. It is a plain browser script with no exports, so it is
// exercised the way the browser drives it: build the DOM it expects, import
// it, then interact through the dropzone, the nav, and the clock. Nothing in
// app.js is modified to make it testable.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const markup = readFileSync(join(here, "index.html"), "utf8");
const BODY = markup.slice(markup.indexOf("<body>") + 6, markup.indexOf("</body>"));

let fetchMock;

/** Rebuild the page and re-run app.js against it, as a page load would.
 *
 * app.js asks GET /auth/me on load, because the session cookie is HttpOnly and
 * the page cannot tell whether it is signed in by looking. That call is
 * answered here and then cleared from the mock, so each test's assertions
 * index from its own first request rather than from the identity check.
 * `loadSignedOut` is for the tests that care about the signed-out half.
 */
async function loadApp({ signedIn = true, role = "user", legacy = true } = {}) {
  document.body.innerHTML = BODY;
  vi.resetModules();
  fetchMock.mockResolvedValueOnce(
    signedIn
      ? jsonResponse({ id: "u-1", email: "maya@example.test", role })
      : jsonResponse({ error: "not authenticated" }, false, 401),
  );
  globalThis.FLICKPOND_LEGACY_API = legacy; // Default tests are the frozen pre-Gateway regression.
  await import("./app.js");
  await vi.waitFor(() =>
    expect(fetchMock).toHaveBeenCalledWith(legacy ? "/api/auth/me" : "/api/media/auth/me"),
  );
  await vi.advanceTimersByTimeAsync(0);
  fetchMock.mockClear();
  return {
    dropzone: document.getElementById("dropzone"),
    fileInput: document.getElementById("file-input"),
    browseButton: document.getElementById("browse-button"),
    status: document.getElementById("status"),
    activeJob: document.getElementById("active-job"),
    jobFilename: document.getElementById("job-filename"),
    jobBadge: document.getElementById("job-badge"),
    jobDelete: document.getElementById("job-delete"),
    jobProgress: document.getElementById("job-progress"),
    jobActions: document.getElementById("job-actions"),
    jobRetry: document.getElementById("job-retry"),
    player: document.getElementById("player"),
    auth: document.getElementById("auth"),
    app: document.getElementById("app"),
    authForm: document.getElementById("auth-form"),
    authEmail: document.getElementById("auth-email"),
    authPassword: document.getElementById("auth-password"),
    authStatus: document.getElementById("auth-status"),
    authToggle: document.getElementById("auth-toggle"),
    authSubmit: document.getElementById("auth-submit"),
    who: document.getElementById("who"),
    logout: document.getElementById("logout"),
    navUpload: document.getElementById("nav-upload"),
    navLibrary: document.getElementById("nav-library"),
    navAdmin: document.getElementById("nav-admin"),
    viewUpload: document.getElementById("view-upload"),
    viewLibrary: document.getElementById("view-library"),
    viewAdmin: document.getElementById("view-admin"),
    viewEdit: document.getElementById("view-edit"),
    jobEdit: document.getElementById("job-edit"),
    libraryGrid: document.getElementById("library-grid"),
    libraryEmpty: document.getElementById("library-empty"),
    libraryStatus: document.getElementById("library-status"),
    libraryFilters: document.getElementById("library-filters"),
    libraryPrev: document.getElementById("library-prev"),
    libraryNext: document.getElementById("library-next"),
    libraryPageLabel: document.getElementById("library-page-label"),
    adminTbody: document.getElementById("admin-tbody"),
    adminEmpty: document.getElementById("admin-empty"),
    adminFilters: document.getElementById("admin-filters"),
    adminStatus: document.getElementById("admin-status"),
    adminRetry: document.getElementById("admin-retry"),
    libraryRetry: document.getElementById("library-retry"),
    adminPrev: document.getElementById("admin-prev"),
    adminNext: document.getElementById("admin-next"),
    editBack: document.getElementById("edit-back"),
    editSource: document.getElementById("edit-source"),
    editPlayer: document.getElementById("edit-player"),
    editStatus: document.getElementById("edit-status"),
    editProgress: document.getElementById("edit-progress"),
    editResult: document.getElementById("edit-result"),
    editResultName: document.getElementById("edit-result-name"),
    editResultDownload: document.getElementById("edit-result-download"),
    editResultNote: document.getElementById("edit-result-note"),
    editResultPlayer: document.getElementById("edit-result-player"),
    editForm: document.getElementById("edit-form"),
    editProcess: document.getElementById("edit-process"),
    editHint: document.getElementById("edit-hint"),
    editCrop: document.getElementById("edit-crop"),
    editCropMount: document.getElementById("edit-crop-mount"),
    editClip: document.getElementById("edit-clip"),
    editClipMount: document.getElementById("edit-clip-mount"),
    editDownscale: document.getElementById("edit-downscale"),
    editDownscaleHeight: document.getElementById("edit-downscale-height"),
    editUpscale: document.getElementById("edit-upscale"),
    editUpscaleHeight: document.getElementById("edit-upscale-height"),
    editConvert: document.getElementById("edit-convert"),
    editConvertFormat: document.getElementById("edit-convert-format"),
  };
}

function fileNamed(name = "holiday.mp4", type = "video/mp4") {
  return new File(["data"], name, { type });
}

function chooseFile(input, file = fileNamed()) {
  Object.defineProperty(input, "files", { value: [file], configurable: true });
}

const jsonResponse = (body, ok = true, status = 200) => ({
  ok,
  status,
  json: async () => body,
});

/** Select a file (via the hidden input's change event) and let the upload
 * plus first poll settle -- the dropzone's real trigger, not a form submit. */
async function uploadFile(el, file = fileNamed()) {
  chooseFile(el.fileInput, file);
  el.fileInput.dispatchEvent(new Event("change"));
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
  await vi.advanceTimersByTimeAsync(0);
}

beforeEach(() => {
  fetchMock = vi.fn();
  globalThis.fetch = fetchMock;
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("upload", () => {
  it("posts the chosen file to /upload as multipart", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "job-1", status: "queued" }));

    await uploadFile(el);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/upload");
    expect(init.method).toBe("POST");
    expect(init.body.get("file")).toBeInstanceOf(File);
  });

  it("polls the job id the API returned", async () => {
    const el = await loadApp();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ job_id: "abc-123" }))
      .mockResolvedValueOnce(jsonResponse({ status: "queued" }));

    await uploadFile(el);

    expect(fetchMock.mock.calls[1][0]).toBe("/api/jobs/abc-123");
  });

  it("shows the filename and a queued badge as soon as the job is accepted", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "job-1", status: "queued" }));

    await uploadFile(el, fileNamed("holiday.mp4"));

    expect(el.activeJob.hidden).toBe(false);
    expect(el.jobFilename.textContent).toBe("holiday.mp4");
    expect(el.jobBadge.textContent).toBe("Queued");
  });

  it("ignores a second file dropped while the first upload is still in flight", async () => {
    const el = await loadApp();
    let release;
    fetchMock.mockReturnValueOnce(
      new Promise((resolve) => {
        release = resolve;
      }),
    );

    chooseFile(el.fileInput, fileNamed("first.mp4"));
    el.fileInput.dispatchEvent(new Event("change"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(el.dropzone.classList.contains("busy")).toBe(true);

    // A second selection while the POST is still pending must not double-post.
    chooseFile(el.fileInput, fileNamed("second.mp4"));
    el.fileInput.dispatchEvent(new Event("change"));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    release(jsonResponse({ job_id: "job-1" }));
    await vi.waitFor(() => expect(el.dropzone.classList.contains("busy")).toBe(false));
  });

  it("surfaces the API error message and clears the busy state", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "file too large" }, false, 400));

    await uploadFile(el);

    expect(el.status.textContent).toContain("file too large");
    expect(el.dropzone.classList.contains("busy")).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("falls back to the status code when the error body is unreadable", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error("not json");
      },
    });

    await uploadFile(el);

    expect(el.status.textContent).toContain("500");
  });

  it("reports a network failure rather than hanging", async () => {
    const el = await loadApp();
    fetchMock.mockRejectedValue(new Error("connection refused"));

    await uploadFile(el);

    expect(el.status.textContent).toContain("connection refused");
    expect(el.dropzone.classList.contains("busy")).toBe(false);
  });

  it("clears the previous job's player when a second upload starts", async () => {
    const el = await loadApp();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ job_id: "job-1" }))
      .mockResolvedValueOnce(jsonResponse({ status: "done", output_url: "http://minio/a.mp4" }));
    await uploadFile(el);
    expect(el.player.hidden).toBe(false);

    fetchMock.mockResolvedValue(jsonResponse({ job_id: "job-2", status: "queued" }));
    await uploadFile(el);

    expect(el.player.hidden).toBe(true);
    expect(el.player.querySelector("video")).toBeNull();
    expect(el.jobBadge.textContent).toBe("Queued");
  });

  it("rejects an unsupported type before ever calling the API", async () => {
    const el = await loadApp();

    chooseFile(el.fileInput, fileNamed("notes.pdf", "application/pdf"));
    el.fileInput.dispatchEvent(new Event("change"));

    expect(el.status.textContent).toContain("not a video format");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  // --- deleting the active job straight off the upload page ---------------

  it("asks for confirmation before deleting the active job, and does nothing if declined", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "job-1", status: "queued" }));
    await uploadFile(el);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    fetchMock.mockClear();

    el.jobDelete.dispatchEvent(new Event("click"));

    expect(window.confirm).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(el.activeJob.hidden).toBe(false);
  });

  it("deletes the active job and resets the card once confirmed", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "job-1", status: "queued" }));
    await uploadFile(el);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockClear();
    fetchMock.mockResolvedValueOnce({ ok: true, status: 204, json: async () => ({}) });

    el.jobDelete.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/jobs/job-1");
    expect(init.method).toBe("DELETE");
    expect(el.activeJob.hidden).toBe(true);
    expect(el.status.textContent).toBe("Video deleted.");
  });

  it("stops polling once the active job is deleted", async () => {
    const el = await loadApp();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ job_id: "job-1" }))
      .mockResolvedValue(jsonResponse({ status: "processing" }));
    await uploadFile(el);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockClear();
    fetchMock.mockResolvedValueOnce({ ok: true, status: 204, json: async () => ({}) });

    el.jobDelete.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);
    fetchMock.mockClear();

    await vi.advanceTimersByTimeAsync(10000);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns to the sign-in form if the session expired mid-delete", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "job-1", status: "queued" }));
    await uploadFile(el);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockClear();
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not authenticated" }, false, 401));

    el.jobDelete.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.auth.hidden).toBe(false);
    expect(el.authStatus.textContent).toContain("session expired");
  });

  it("opens the file picker from the dropzone, once per click", async () => {
    const el = await loadApp();
    const picker = vi.spyOn(el.fileInput, "click").mockImplementation(() => {});

    el.dropzone.dispatchEvent(new Event("click"));
    expect(picker).toHaveBeenCalledTimes(1);

    // The browse button sits inside the dropzone, so its click reaches both
    // handlers -- which must still be one trip to the picker, not two.
    el.browseButton.dispatchEvent(new Event("click", { bubbles: true }));
    expect(picker).toHaveBeenCalledTimes(2);
  });

  it("takes a dropped file, and ignores a drop carrying none", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "job-1", status: "queued" }));

    el.dropzone.dispatchEvent(new Event("dragover"));
    expect(el.dropzone.classList.contains("over")).toBe(true);
    el.dropzone.dispatchEvent(new Event("dragleave"));
    expect(el.dropzone.classList.contains("over")).toBe(false);

    const empty = new Event("drop");
    empty.dataTransfer = { files: [] };
    el.dropzone.dispatchEvent(empty);
    expect(fetchMock).not.toHaveBeenCalled();

    const withFile = new Event("drop");
    withFile.dataTransfer = { files: [fileNamed()] };
    el.dropzone.dispatchEvent(withFile);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
  });

  it("refuses a file over the size limit without asking the API", async () => {
    const el = await loadApp();
    const huge = fileNamed("huge.mp4");
    Object.defineProperty(huge, "size", { value: 200 * 1024 * 1024 });

    chooseFile(el.fileInput, huge);
    el.fileInput.dispatchEvent(new Event("change"));

    expect(el.status.textContent).toContain("100MB");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("returns to the sign-in form if the session expired during the upload", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not authenticated" }, false, 401));

    await uploadFile(el);

    expect(el.auth.hidden).toBe(false);
    expect(el.authStatus.textContent).toContain("session expired");
    expect(el.dropzone.classList.contains("busy")).toBe(false);
  });

  it("does nothing when there is no active job to delete", async () => {
    const el = await loadApp();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    el.jobDelete.dispatchEvent(new Event("click"));

    expect(window.confirm).not.toHaveBeenCalled();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps the card and says why when the delete is refused", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "job-1", status: "queued" }));
    await uploadFile(el);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockClear();
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not found" }, false, 404));

    el.jobDelete.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.status.textContent).toContain("not found");
    expect(el.activeJob.hidden).toBe(false);
  });

  it("reports a network failure while deleting rather than hanging", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValue(jsonResponse({ job_id: "job-1", status: "queued" }));
    await uploadFile(el);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockClear();
    fetchMock.mockRejectedValueOnce(new Error("connection refused"));

    el.jobDelete.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.status.textContent).toContain("connection refused");
  });

  it("retries a failed stored source without uploading again", async () => {
    const el = await loadApp();
    el.jobRetry.dispatchEvent(new Event("click"));
    expect(fetchMock).not.toHaveBeenCalled();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "job-1" }))
      .mockResolvedValueOnce(jsonResponse({ id: "job-1", status: "failed" }));
    await uploadFile(el);
    fetchMock.mockClear();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "job-1" }))
      .mockResolvedValue(jsonResponse({ id: "job-1", status: "queued" }));
    el.jobRetry.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/jobs/job-1/retry");
    expect(init.method).toBe("POST");
    expect(init.body).toBeUndefined();
    expect(init.headers["Idempotency-Key"]).toMatch(/^[a-f0-9-]{36}$/);
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/upload")).toBe(false);
  });
});

describe("polling", () => {
  /** Upload, then have every poll return the given job document. */
  async function pollReturning(job) {
    const el = await loadApp();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ job_id: "job-1" }))
      .mockResolvedValue(jsonResponse(job));
    await uploadFile(el);
    return el;
  }

  it("shows the player and stops polling once the job is done", async () => {
    const el = await pollReturning({ status: "done", output_url: "http://minio/out.mp4" });

    expect(el.player.querySelector("video").getAttribute("src")).toBe("http://minio/out.mp4");
    expect(el.player.hidden).toBe(false);
    expect(el.jobBadge.textContent).toBe("Done");
    await vi.advanceTimersByTimeAsync(10000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("shows the error, offers a retry, and stops polling once the job has failed", async () => {
    const el = await pollReturning({ status: "failed", error: "source missing" });

    expect(el.status.textContent).toContain("source missing");
    expect(el.player.hidden).toBe(true);
    expect(el.jobActions.hidden).toBe(false);
    await vi.advanceTimersByTimeAsync(10000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("does not print undefined when a failed job carries no error text", async () => {
    const el = await pollReturning({ status: "failed" });

    expect(el.status.textContent).toContain("Unknown error");
    expect(el.status.textContent).not.toContain("undefined");
  });

  it("stops polling a cancelled job without offering a retry", async () => {
    const el = await pollReturning({ status: "cancelled", error: "Processing was cancelled" });

    expect(el.status.textContent).toBe("Processing was cancelled.");
    expect(el.jobBadge.textContent).toBe("Cancelled");
    expect(el.jobRetry.hidden).toBe(true);
    await vi.advanceTimersByTimeAsync(10000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it.each([
    ["accepted", "Accepted..."],
    ["queued", "Queued..."],
    ["processing", "Processing..."],
  ])("keeps polling every 2s while the job is %s", async (status, label) => {
    const el = await pollReturning({ status });

    expect(el.status.textContent).toBe(label);
    await vi.advanceTimersByTimeAsync(10000);
    // 1 upload + 1 immediate poll + 5 more at 2s intervals over the next 10s.
    expect(fetchMock).toHaveBeenCalledTimes(7);
  });

  it("shows the progress sweep only while the job is processing", async () => {
    const el = await pollReturning({ status: "processing" });

    expect(el.jobProgress.hidden).toBe(false);
  });

  // --- a job that never finishes (P4) -------------------------------------

  /** 30 polls at 2s: the point where the page starts saying it is slow. */
  const SLOW_AFTER_MS = 30 * 2000;

  it("says so once a job has been processing far longer than it should", async () => {
    const el = await pollReturning({ status: "processing" });
    expect(el.status.textContent).toBe("Processing...");

    await vi.advanceTimersByTimeAsync(SLOW_AFTER_MS);

    expect(el.status.textContent).toContain("longer than expected");
    expect(el.status.textContent).toContain("job-1");
  });

  it("hands the form back so a stuck job does not lock the page", async () => {
    const el = await pollReturning({ status: "processing" });
    expect(el.jobActions.hidden).toBe(true);

    await vi.advanceTimersByTimeAsync(SLOW_AFTER_MS);

    expect(el.jobActions.hidden).toBe(false);
  });

  it("keeps polling after saying it is slow, because slow is not failed", async () => {
    const el = await pollReturning({ status: "processing" });
    await vi.advanceTimersByTimeAsync(SLOW_AFTER_MS);
    const before = fetchMock.mock.calls.length;

    await vi.advanceTimersByTimeAsync(2000);

    expect(fetchMock.mock.calls.length).toBe(before + 1);
    expect(el.status.textContent).not.toContain("failed");
  });

  it("recovers normally if a long-running job does eventually finish", async () => {
    const el = await pollReturning({ status: "processing" });
    await vi.advanceTimersByTimeAsync(SLOW_AFTER_MS);
    expect(el.status.textContent).toContain("longer than expected");

    fetchMock.mockResolvedValue(jsonResponse({ status: "done", output_url: "http://minio/late.mp4" }));
    await vi.advanceTimersByTimeAsync(2000);

    expect(el.status.textContent).toBe("Processing complete.");
    expect(el.player.querySelector("video").getAttribute("src")).toBe("http://minio/late.mp4");
  });

  it("shows an unrecognised status verbatim rather than blanking the UI", async () => {
    const el = await pollReturning({ status: "paused" });

    expect(el.status.textContent).toBe("paused");
  });

  it("a new upload cancels the previous job's scheduled poll", async () => {
    const el = await pollReturning({ status: "queued" });
    const afterFirst = fetchMock.mock.calls.length;

    fetchMock.mockResolvedValue(jsonResponse({ job_id: "job-2", status: "done" }));
    await uploadFile(el);
    const afterSecond = fetchMock.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10000);

    expect(fetchMock.mock.calls.length).toBe(afterSecond);
    expect(afterSecond).toBeGreaterThan(afterFirst);
  });
});

describe("signing in", () => {
  it("shows the sign-in form and hides the app when not signed in", async () => {
    const el = await loadApp({ signedIn: false });

    expect(el.auth.hidden).toBe(false);
    expect(el.app.hidden).toBe(true);
  });

  it("shows the app and the signed-in address when /auth/me answers", async () => {
    const el = await loadApp();

    expect(el.auth.hidden).toBe(true);
    expect(el.app.hidden).toBe(false);
    expect(el.who.textContent).toBe("maya@example.test");
  });

  it("posts credentials as JSON and reveals the app on success", async () => {
    const el = await loadApp({ signedIn: false });
    el.authEmail.value = "maya@example.test";
    el.authPassword.value = "hunter2hunter2";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ id: "u-1", email: "maya@example.test", role: "user" }),
    );

    el.authForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/login");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      email: "maya@example.test",
      password: "hunter2hunter2",
    });
    expect(el.app.hidden).toBe(false);
  });

  it("never attaches a token, because it cannot read one", async () => {
    // The session cookie is HttpOnly. If a future change starts putting an
    // Authorization header on here, the token has come from somewhere a script
    // can read -- which is the thing this design exists to prevent.
    const el = await loadApp({ signedIn: false });
    el.authEmail.value = "maya@example.test";
    el.authPassword.value = "hunter2hunter2";
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ id: "u-1", email: "maya@example.test", role: "user" }),
    );

    el.authForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());

    for (const [, init] of fetchMock.mock.calls) {
      expect(init?.headers?.Authorization).toBeUndefined();
    }
  });

  it("does not say which half of the credentials was wrong", async () => {
    const el = await loadApp({ signedIn: false });
    el.authEmail.value = "maya@example.test";
    el.authPassword.value = "wrongwrongwrong";
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "invalid" }, false, 401));

    el.authForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.authStatus.textContent).toBe("Incorrect email or password.");
    expect(el.app.hidden).toBe(true);
  });

  it("reports a taken address on register", async () => {
    const el = await loadApp({ signedIn: false });
    el.authToggle.dispatchEvent(new Event("click"));
    el.authEmail.value = "taken@example.test";
    el.authPassword.value = "hunter2hunter2";
    fetchMock.mockResolvedValueOnce(jsonResponse({}, false, 409));

    el.authForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/auth/register");
    expect(el.authStatus.textContent).toContain("already registered");
  });

  it("signs out through the server, because a script cannot clear the cookie", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({}, true, 204));

    el.logout.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/auth/logout");
    expect(init.method).toBe("POST");
    expect(el.auth.hidden).toBe(false);
    expect(el.app.hidden).toBe(true);
  });

  it("returns to the sign-in form when a session expires mid-poll", async () => {
    const el = await loadApp();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ job_id: "job-1" }))
      .mockResolvedValue(jsonResponse({ error: "not authenticated" }, false, 401));

    await uploadFile(el);

    expect(el.auth.hidden).toBe(false);
    expect(el.authStatus.textContent).toContain("session expired");
  });

  it("hides the admin tab for an ordinary user", async () => {
    const el = await loadApp({ role: "user" });

    expect(el.navAdmin.hidden).toBe(true);
  });

  it("shows the admin tab for an operator", async () => {
    const el = await loadApp({ role: "operator" });

    expect(el.navAdmin.hidden).toBe(false);
  });

  it("asks for a valid address and a long enough password on 422", async () => {
    const el = await loadApp({ signedIn: false });
    el.authEmail.value = "not-an-address";
    el.authPassword.value = "short";
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: [] }, false, 422));

    el.authForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.authStatus.textContent).toContain("at least 8 characters");
  });

  it("reports a status the sign-in form has no wording for", async () => {
    const el = await loadApp({ signedIn: false });
    el.authEmail.value = "maya@example.test";
    el.authPassword.value = "hunter2hunter2";
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "boom" }, false, 500));

    el.authForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.authStatus.textContent).toContain("500");
  });

  it("reports a network failure on sign-in instead of hanging", async () => {
    const el = await loadApp({ signedIn: false });
    el.authEmail.value = "maya@example.test";
    el.authPassword.value = "hunter2hunter2";
    fetchMock.mockRejectedValueOnce(new Error("connection refused"));

    el.authForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.authStatus.textContent).toContain("connection refused");
    // The button has to come back, or the form is dead after one failure.
    expect(el.authSubmit.disabled).toBe(false);
  });

  it("shows the sign-in form when the API cannot be reached at all", async () => {
    fetchMock.mockRejectedValueOnce(new Error("connection refused"));

    const el = await loadApp();

    expect(el.auth.hidden).toBe(false);
    expect(el.app.hidden).toBe(true);
  });

  it("refuses the admin view for an ordinary user, however it is asked for", async () => {
    const el = await loadApp({ role: "user" });

    // The tab is hidden, not disabled: jsdom clicks it happily, and a future
    // deep link would arrive the same way.
    el.navAdmin.dispatchEvent(new Event("click"));

    expect(el.viewAdmin.hidden).toBe(true);
    expect(el.viewUpload.hidden).toBe(false);
  });
});

describe("library", () => {
  const JOBS = [
    { id: "1", filename: "holiday.mp4", status: "done", output_url: "http://minio/holiday.mp4" },
    { id: "2", filename: "recap.mov", status: "processing" },
    { id: "3", filename: "broken.mkv", status: "failed", error: "corrupt file" },
  ];

  it("fetches the caller's own jobs when the tab is opened", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse(JOBS));

    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/jobs?limit=12&offset=0");
    expect(el.viewLibrary.hidden).toBe(false);
    expect(el.viewUpload.hidden).toBe(true);
  });

  it("renders one card per job, named by filename", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse(JOBS));

    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    const names = [...el.libraryGrid.querySelectorAll(".video-filename")].map((n) => n.textContent);
    expect(names).toEqual(["holiday.mp4", "recap.mov", "broken.mkv"]);
  });

  it("shows the empty state when there are no jobs at all", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.libraryEmpty.hidden).toBe(false);
    expect(el.libraryGrid.hidden).toBe(true);
  });

  it("filters client-side, with no extra request", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse(JOBS));
    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);
    fetchMock.mockClear();

    el.libraryFilters.querySelector('[data-status="failed"]').dispatchEvent(new Event("click"));

    const names = [...el.libraryGrid.querySelectorAll(".video-filename")].map((n) => n.textContent);
    expect(names).toEqual(["broken.mkv"]);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("pages forward by re-fetching with the next offset", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse(JOBS));
    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);
    fetchMock.mockClear();
    fetchMock.mockResolvedValueOnce(jsonResponse([]));

    el.libraryNext.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/jobs?limit=12&offset=12");
  });

  // --- deleting a video: an accidental upload, or general cleanup --------

  async function openLibraryWith(el, jobs) {
    fetchMock.mockResolvedValueOnce(jsonResponse(jobs));
    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);
    fetchMock.mockClear();
  }

  function deleteButtonFor(el, filename) {
    const card = [...el.libraryGrid.querySelectorAll(".video-card")].find((c) =>
      c.querySelector(".video-filename").textContent === filename,
    );
    return card.querySelector(".card-delete");
  }

  it("asks for confirmation before deleting, and does nothing if declined", async () => {
    const el = await loadApp();
    await openLibraryWith(el, JOBS);
    vi.spyOn(window, "confirm").mockReturnValue(false);

    deleteButtonFor(el, "holiday.mp4").dispatchEvent(new Event("click", { bubbles: true }));

    expect(window.confirm).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
    const names = [...el.libraryGrid.querySelectorAll(".video-filename")].map((n) => n.textContent);
    expect(names).toContain("holiday.mp4");
  });

  it("deletes the video and removes its card once confirmed", async () => {
    const el = await loadApp();
    await openLibraryWith(el, JOBS);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockResolvedValueOnce({ ok: true, status: 204, json: async () => ({}) });

    deleteButtonFor(el, "holiday.mp4").dispatchEvent(new Event("click", { bubbles: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/jobs/1");
    expect(init.method).toBe("DELETE");
    const names = [...el.libraryGrid.querySelectorAll(".video-filename")].map((n) => n.textContent);
    expect(names).toEqual(["recap.mov", "broken.mkv"]);
  });

  it("does not also open the inline player when the delete button is clicked", async () => {
    const el = await loadApp();
    await openLibraryWith(el, JOBS);
    vi.spyOn(window, "confirm").mockReturnValue(false);

    const card = [...el.libraryGrid.querySelectorAll(".video-card")].find((c) =>
      c.querySelector(".video-filename").textContent === "holiday.mp4",
    );
    deleteButtonFor(el, "holiday.mp4").dispatchEvent(new Event("click", { bubbles: true }));

    expect(card.querySelector("video")).toBeNull();
  });

  it("shows an error and keeps the card if the delete fails", async () => {
    const el = await loadApp();
    await openLibraryWith(el, JOBS);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not found" }, false, 404));

    deleteButtonFor(el, "holiday.mp4").dispatchEvent(new Event("click", { bubbles: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.libraryStatus.textContent).toContain("not found");
    const names = [...el.libraryGrid.querySelectorAll(".video-filename")].map((n) => n.textContent);
    expect(names).toContain("holiday.mp4");
  });

  it("returns to the sign-in form if the session expired mid-delete", async () => {
    const el = await loadApp();
    await openLibraryWith(el, JOBS);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not authenticated" }, false, 401));

    deleteButtonFor(el, "holiday.mp4").dispatchEvent(new Event("click", { bubbles: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.auth.hidden).toBe(false);
    expect(el.authStatus.textContent).toContain("session expired");
  });

  it("shows a status the badge has no styling for, verbatim", async () => {
    const el = await loadApp();
    await openLibraryWith(el, [{ id: "9", filename: "odd.mp4", status: "paused" }]);

    expect(el.libraryGrid.querySelector(".badge").textContent).toContain("paused");
  });

  it("keeps the card and says why when a library delete is refused", async () => {
    const el = await loadApp();
    await openLibraryWith(el, JOBS);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not found" }, false, 404));

    deleteButtonFor(el, "holiday.mp4").dispatchEvent(new Event("click", { bubbles: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.libraryStatus.textContent).toContain("not found");
  });

  it("reports a network failure while deleting a library card", async () => {
    const el = await loadApp();
    await openLibraryWith(el, JOBS);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockRejectedValueOnce(new Error("connection refused"));

    deleteButtonFor(el, "holiday.mp4").dispatchEvent(new Event("click", { bubbles: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.libraryStatus.textContent).toContain("connection refused");
  });

  it("returns to the sign-in form when the library request says the session expired", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not authenticated" }, false, 401));

    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.auth.hidden).toBe(false);
    expect(el.authStatus.textContent).toContain("session expired");
  });

  it("says the library could not be loaded rather than showing it empty when the list request fails", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "boom" }, false, 500));

    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.libraryEmpty.hidden).toBe(true);
    expect(el.libraryGrid.hidden).toBe(true);
    expect(el.libraryStatus.textContent).toContain("Could not load");
    expect(el.libraryRetry.hidden).toBe(false);
  });

  it("reports a library load error when the list request cannot be made at all", async () => {
    const el = await loadApp();
    fetchMock.mockRejectedValueOnce(new Error("connection refused"));

    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.libraryEmpty.hidden).toBe(true);
    expect(el.libraryStatus.textContent).toContain("Could not load");
  });

  it("pages back without going below the first page", async () => {
    const el = await loadApp();
    await openLibraryWith(el, JOBS);
    fetchMock.mockResolvedValueOnce(jsonResponse(JOBS));

    el.libraryPrev.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/jobs?limit=12&offset=0");
  });
});

describe("admin", () => {
  const ROWS = [
    { id: "1", filename: "a.mp4", status: "done", output_url: "http://minio/a.mp4" },
    { id: "2", filename: "b.mp4", status: "queued" },
  ];

  it("fetches every job when an operator opens the tab", async () => {
    const el = await loadApp({ role: "operator" });
    fetchMock.mockResolvedValueOnce(jsonResponse(ROWS));

    el.navAdmin.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/admin/jobs?limit=12&offset=0");
    expect(el.viewAdmin.hidden).toBe(false);
  });

  it("renders one row per job", async () => {
    const el = await loadApp({ role: "operator" });
    fetchMock.mockResolvedValueOnce(jsonResponse(ROWS));

    el.navAdmin.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.adminTbody.querySelectorAll("tr").length).toBe(2);
  });

  it("falls back to the upload view if the API refuses with 403", async () => {
    const el = await loadApp({ role: "operator" });
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "operator role required" }, false, 403));

    el.navAdmin.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.viewUpload.hidden).toBe(false);
    expect(el.viewAdmin.hidden).toBe(true);
  });

  // --- previewing without downloading, and deleting any user's upload ----

  async function openAdminWith(el, rows) {
    fetchMock.mockResolvedValueOnce(jsonResponse(rows));
    el.navAdmin.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);
    fetchMock.mockClear();
  }

  function rowFor(el, filename) {
    return [...el.adminTbody.querySelectorAll("tr")].find(
      (r) => r.firstElementChild.textContent === filename,
    );
  }

  it("plays a done job inline rather than linking to a downloadable URL", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);

    const row = rowFor(el, "a.mp4");
    expect(row.querySelector("a")).toBeNull();
    const watchButton = row.querySelector(".admin-watch");
    expect(watchButton.textContent).toBe("Watch");

    watchButton.dispatchEvent(new Event("click"));

    expect(fetchMock).not.toHaveBeenCalled();
    const video = row.querySelector("video");
    expect(video.getAttribute("src")).toBe("http://minio/a.mp4");
    expect(watchButton.textContent).toBe("Hide");
  });

  it("hides the player again on a second click", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);
    const row = rowFor(el, "a.mp4");
    const watchButton = row.querySelector(".admin-watch");

    watchButton.dispatchEvent(new Event("click"));
    watchButton.dispatchEvent(new Event("click"));

    expect(row.querySelector("video")).toBeNull();
    expect(watchButton.textContent).toBe("Watch");
  });

  it("shows no preview control for a job with no output yet", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);

    const row = rowFor(el, "b.mp4");

    expect(row.querySelector(".admin-watch")).toBeNull();
    expect(row.querySelector("a")).toBeNull();
  });

  it("asks for confirmation before deleting, and does nothing if declined", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);
    vi.spyOn(window, "confirm").mockReturnValue(false);

    rowFor(el, "a.mp4").querySelector(".card-delete").dispatchEvent(new Event("click"));

    expect(window.confirm).toHaveBeenCalledOnce();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(rowFor(el, "a.mp4")).toBeTruthy();
  });

  it("deletes any user's job through the unscoped admin route", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockResolvedValueOnce({ ok: true, status: 204, json: async () => ({}) });

    rowFor(el, "a.mp4").querySelector(".card-delete").dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/admin/jobs/1");
    expect(init.method).toBe("DELETE");
    expect(el.adminTbody.querySelectorAll("tr").length).toBe(1);
    expect(rowFor(el, "a.mp4")).toBeUndefined();
  });

  it("shows an error and keeps the row if the admin delete fails", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not found" }, false, 404));

    rowFor(el, "a.mp4").querySelector(".card-delete").dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.adminStatus.textContent).toContain("not found");
    expect(rowFor(el, "a.mp4")).toBeTruthy();
  });

  it("filters the table without asking the API again", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);
    fetchMock.mockClear();

    el.adminFilters.querySelector('[data-status="queued"]').dispatchEvent(new Event("click"));

    expect(fetchMock).not.toHaveBeenCalled();
    expect(el.adminTbody.querySelectorAll("tr")).toHaveLength(1);
  });

  it("offers a preview for a job whose only source is the ladder", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, [
      { id: "9", filename: "c.mp4", status: "done", hls_url: "/api/jobs/9/hls/master.m3u8" },
    ]);

    expect(rowFor(el, "c.mp4").querySelector(".admin-watch")).not.toBeNull();
  });

  it("returns to the sign-in form when the admin list says the session expired", async () => {
    const el = await loadApp({ role: "operator" });
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not authenticated" }, false, 401));

    el.navAdmin.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.auth.hidden).toBe(false);
    expect(el.authStatus.textContent).toContain("session expired");
  });

  it("reports an admin load error rather than an empty table when the list request fails", async () => {
    const el = await loadApp({ role: "operator" });
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "boom" }, false, 500));

    el.navAdmin.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.adminEmpty.hidden).toBe(true);
    expect(el.adminStatus.textContent).toContain("Could not load");
    expect(el.adminRetry.hidden).toBe(false);
  });

  it("reports an admin load error when the list request cannot be made at all", async () => {
    const el = await loadApp({ role: "operator" });
    fetchMock.mockRejectedValueOnce(new Error("connection refused"));

    el.navAdmin.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.adminEmpty.hidden).toBe(true);
    expect(el.adminStatus.textContent).toContain("Could not load");
  });

  it("returns to the sign-in form if the session expired mid-admin-delete", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not authenticated" }, false, 401));

    rowFor(el, "a.mp4").querySelector(".card-delete").dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.auth.hidden).toBe(false);
    expect(el.authStatus.textContent).toContain("session expired");
  });

  it("leaves the admin view if a delete says the operator role is gone", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "operator role required" }, false, 403));

    rowFor(el, "a.mp4").querySelector(".card-delete").dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.viewAdmin.hidden).toBe(true);
    expect(el.viewUpload.hidden).toBe(false);
  });

  it("reports a network failure while deleting another user's job", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    fetchMock.mockRejectedValueOnce(new Error("connection refused"));

    rowFor(el, "a.mp4").querySelector(".card-delete").dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.adminStatus.textContent).toContain("connection refused");
  });

  it("pages forward by re-fetching with the next offset", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);
    fetchMock.mockResolvedValueOnce(jsonResponse(ROWS));

    el.adminNext.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/admin/jobs?limit=12&offset=12");
  });

  it("pages back without going below the first page of jobs", async () => {
    const el = await loadApp({ role: "operator" });
    await openAdminWith(el, ROWS);
    fetchMock.mockResolvedValueOnce(jsonResponse(ROWS));

    el.adminPrev.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/admin/jobs?limit=12&offset=0");
  });
});

// ---------------------------------------------------------------------------
// The player. Plyr and hls.js arrive as separate vendored scripts that
// index.html loads, so these tests bring their own stand-ins. What is worth
// pinning down is not their internals but the app's half of the bargain:
// which source a job gets, where the level list comes from, and that nothing
// is left running once a card is closed or re-rendered.
// ---------------------------------------------------------------------------

const HLS_EVENTS = { MANIFEST_PARSED: "manifestParsed", ERROR: "error" };

/** Stand-in for the vendored Plyr: it only augments the element it was handed,
 *  so the fake's job is to record whether it was ever destroyed. */
class FakePlyr {
  constructor(element, config) {
    this.media = element;
    this.config = config;
    this.quality = undefined;
    this.destroyed = false;
    // What the real one does to the element it takes over.
    element.removeAttribute("controls");
    FakePlyr.created.push(this);
  }

  destroy() {
    this.destroyed = true;
  }
}
FakePlyr.created = [];

/** Stand-in for the vendored hls.js, with just enough surface for the app's
 *  half: the level list, the two events it listens for, and destroy(). */
class FakeHls {
  constructor() {
    this.levels = FakeHls.levels;
    this.handlers = {};
    this.attachedTo = null;
    this.loadedSource = null;
    this.currentLevel = -1;
    this.destroyed = false;
    FakeHls.instances.push(this);
  }

  static isSupported() {
    return true;
  }

  on(event, handler) {
    this.handlers[event] = [...(this.handlers[event] ?? []), handler];
  }

  /** Fire an hls.js event at the app's own listeners. */
  emit(event, data = {}) {
    for (const handler of this.handlers[event] ?? []) handler(event, data);
  }

  attachMedia(video) {
    this.attachedTo = video;
  }

  loadSource(url) {
    this.loadedSource = url;
  }

  destroy() {
    this.destroyed = true;
  }
}
FakeHls.instances = [];
FakeHls.Events = HLS_EVENTS;
FakeHls.levels = [{ height: 720 }, { height: 480 }, { height: 360 }];

describe("player", () => {
  const DONE = {
    id: "1",
    filename: "holiday.mp4",
    status: "done",
    output_url: "http://minio/holiday.mp4",
  };
  const ADAPTIVE = { ...DONE, hls_url: "/api/jobs/1/hls/master.m3u8" };

  beforeEach(() => {
    FakePlyr.created = [];
    FakeHls.instances = [];
  });

  afterEach(() => {
    // The libraries are globals the page loads; leaving them behind would make
    // every later test run with a player it did not ask for.
    delete window.Plyr;
    delete window.Hls;
  });

  /** The page as index.html delivers it: both libraries loaded. */
  async function loadAppWithLibraries(options) {
    const el = await loadApp(options);
    window.Plyr = FakePlyr;
    window.Hls = FakeHls;
    return el;
  }

  async function openLibrary(el, jobs) {
    fetchMock.mockResolvedValueOnce(jsonResponse(jobs));
    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);
  }

  function cardFor(el, filename) {
    return [...el.libraryGrid.querySelectorAll(".video-card")].find(
      (c) => c.querySelector(".video-filename").textContent === filename,
    );
  }

  function play(card) {
    card.querySelector(".video-thumb").dispatchEvent(new Event("click"));
  }

  function videoIn(card) {
    return card.querySelector(".player-host video");
  }

  it("plays a job's MP4 through Plyr when it has no ladder", async () => {
    const el = await loadAppWithLibraries();
    await openLibrary(el, [DONE]);

    play(cardFor(el, "holiday.mp4"));

    expect(FakePlyr.created).toHaveLength(1);
    expect(FakePlyr.created[0].media.getAttribute("src")).toBe(DONE.output_url);
    // No ladder, no level list -- and therefore no quality menu to offer.
    expect(FakePlyr.created[0].config.quality).toBeUndefined();
  });

  it("plays a job's ladder through hls.js rather than its MP4", async () => {
    const el = await loadAppWithLibraries();
    await openLibrary(el, [ADAPTIVE]);
    const card = cardFor(el, "holiday.mp4");

    play(card);

    const hls = FakeHls.instances[0];
    expect(hls.attachedTo).toBe(videoIn(card));
    expect(hls.loadedSource).toBe(ADAPTIVE.hls_url);
  });

  it("waits for the manifest, so the menu lists the ladder's own levels", async () => {
    const el = await loadAppWithLibraries();
    await openLibrary(el, [ADAPTIVE]);

    play(cardFor(el, "holiday.mp4"));

    // Plyr builds its quality menu once, from the list it is handed: creating
    // it before the levels are known would offer renditions that might not be
    // in the ladder at all, including an upscaled 720p a 480p source lacks.
    expect(FakePlyr.created).toHaveLength(0);

    FakeHls.instances[0].emit(HLS_EVENTS.MANIFEST_PARSED);

    expect(FakePlyr.created).toHaveLength(1);
    expect(FakePlyr.created[0].config.quality.forced).toBe(true);
    expect(FakePlyr.created[0].config.quality.options).toEqual([0, 720, 480, 360]);
    expect(FakePlyr.created[0].config.i18n.qualityLabel).toEqual({ 0: "Auto" });
    // The settings menu reads the player's current quality, and "undefined" is
    // what it says unless the app tells it where the ladder starts.
    expect(FakePlyr.created[0].quality).toBe(0);
  });

  it("switches the hls.js level when a quality is picked, and back to auto", async () => {
    const el = await loadAppWithLibraries();
    await openLibrary(el, [ADAPTIVE]);
    play(cardFor(el, "holiday.mp4"));
    const hls = FakeHls.instances[0];
    hls.emit(HLS_EVENTS.MANIFEST_PARSED);

    const { onChange } = FakePlyr.created[0].config.quality;
    onChange(480);
    expect(hls.currentLevel).toBe(1);

    onChange(0);
    expect(hls.currentLevel).toBe(-1);
  });

  it("destroys both libraries when the card is closed again", async () => {
    const el = await loadAppWithLibraries();
    await openLibrary(el, [ADAPTIVE]);
    const card = cardFor(el, "holiday.mp4");

    play(card);
    const hls = FakeHls.instances[0];
    hls.emit(HLS_EVENTS.MANIFEST_PARSED);
    play(card);

    expect(hls.destroyed).toBe(true);
    expect(FakePlyr.created[0].destroyed).toBe(true);
    expect(card.querySelector("video")).toBeNull();
    expect(card.querySelector(".player-host")).toBeNull();
  });

  it("tears the player down before a re-render throws its card away", async () => {
    const el = await loadAppWithLibraries();
    await openLibrary(el, [DONE]);
    play(cardFor(el, "holiday.mp4"));

    // Filtering re-renders the whole grid, cards and players included.
    el.libraryFilters.querySelector('[data-status="failed"]').dispatchEvent(new Event("click"));

    expect(FakePlyr.created[0].destroyed).toBe(true);
    expect(el.libraryGrid.querySelector(".player-host")).toBeNull();
  });

  it("does not collapse the card when the player itself is clicked", async () => {
    const el = await loadAppWithLibraries();
    await openLibrary(el, [DONE]);
    const card = cardFor(el, "holiday.mp4");
    play(card);
    const host = card.querySelector(".player-host");

    // Every control in the player sits inside the element whose click opened
    // it, so a press of play would otherwise close the card it is playing in.
    host.dispatchEvent(new Event("click", { bubbles: true }));

    expect(card.querySelector(".player-host")).toBe(host);
  });

  it("leaves a plain playable video behind when Plyr never loads", async () => {
    const el = await loadApp();
    await openLibrary(el, [ADAPTIVE]);

    play(cardFor(el, "holiday.mp4"));

    const video = videoIn(cardFor(el, "holiday.mp4"));
    expect(video.getAttribute("src")).toBe(DONE.output_url);
    expect(video.controls).toBe(true);
  });

  it("falls back to the MP4 when hls.js is missing but a ladder exists", async () => {
    const el = await loadApp();
    window.Plyr = FakePlyr;
    await openLibrary(el, [ADAPTIVE]);

    play(cardFor(el, "holiday.mp4"));

    expect(videoIn(cardFor(el, "holiday.mp4")).getAttribute("src")).toBe(DONE.output_url);
    expect(FakePlyr.created[0].config.quality).toBeUndefined();
  });

  it("drops back to the MP4 when the ladder fails fatally", async () => {
    const el = await loadAppWithLibraries();
    await openLibrary(el, [ADAPTIVE]);
    play(cardFor(el, "holiday.mp4"));
    const hls = FakeHls.instances[0];
    hls.emit(HLS_EVENTS.MANIFEST_PARSED);

    hls.emit(HLS_EVENTS.ERROR, { fatal: true });
    await vi.advanceTimersByTimeAsync(0);

    expect(videoIn(cardFor(el, "holiday.mp4")).getAttribute("src")).toBe(DONE.output_url);
    // Rebuilt rather than repointed: the first player's menu was built around
    // a ladder that turned out not to play.
    expect(FakePlyr.created[1].config.quality).toBeUndefined();
    expect(FakeHls.instances).toHaveLength(1);
    expect(hls.destroyed).toBe(true);
  });

  it("does not build a player into a card collapsed while the manifest loaded", async () => {
    const el = await loadAppWithLibraries();
    await openLibrary(el, [ADAPTIVE]);
    const card = cardFor(el, "holiday.mp4");

    play(card);
    const hls = FakeHls.instances[0];
    play(card);

    hls.emit(HLS_EVENTS.MANIFEST_PARSED);

    expect(FakePlyr.created).toHaveLength(0);
    expect(hls.destroyed).toBe(true);
  });

  it("plays the upload card's finished job through Plyr too", async () => {
    const el = await loadAppWithLibraries();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ job_id: "job-1" }))
      .mockResolvedValue(jsonResponse({ status: "done", output_url: DONE.output_url }));

    await uploadFile(el);

    expect(FakePlyr.created).toHaveLength(1);
    expect(FakePlyr.created[0].media.getAttribute("src")).toBe(DONE.output_url);
  });

  it("gives an operator's admin preview the same player", async () => {
    const el = await loadAppWithLibraries({ role: "operator" });
    fetchMock.mockResolvedValueOnce(jsonResponse([DONE]));
    el.navAdmin.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    el.adminTbody.querySelector(".admin-watch").dispatchEvent(new Event("click"));

    expect(FakePlyr.created).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// The editing panel. It is one view over the contract in sprint3-plan.md §1,
// so these tests are about two things: what it sends, and what it refuses to
// send. Crop and clip belong to other tracks, so the seam with them is a
// stand-in here -- EDITOR-COMPONENTS.md is the contract they implement.
// ---------------------------------------------------------------------------

describe("editor", () => {
  const SOURCE = {
    id: "1",
    filename: "holiday.mp4",
    status: "done",
    output_url: "http://minio/holiday.mp4",
  };

  beforeEach(() => {
    FakePlyr.created = [];
    window.Plyr = FakePlyr;
  });

  afterEach(() => {
    delete window.Plyr;
    delete window.mountCropBox;
    delete window.mountClipScrubber;
  });

  async function openLibraryWith(el, jobs) {
    fetchMock.mockResolvedValueOnce(jsonResponse(jobs));
    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);
    fetchMock.mockClear();
  }

  /** Open the editor from the first Library card that offers it. */
  async function openEditor(el, jobs = [SOURCE]) {
    await openLibraryWith(el, jobs);
    const button = el.libraryGrid.querySelector(".card-edit");
    expect(button, "no card offered Edit").toBeTruthy();
    button.dispatchEvent(new Event("click"));
    return el;
  }

  /** A stand-in for one of B's or C's components: it records the element it
   *  was handed, and reports whatever the test tells it to. */
  function fakeComponent() {
    return {
      calls: [],
      cleanup: vi.fn(),
      mount(video, onChange) {
        this.calls.push({ video, onChange });
        return this.cleanup;
      },
      report(selection) {
        this.calls.at(-1).onChange(selection);
      },
    };
  }

  function submit(el) {
    el.editForm.dispatchEvent(new Event("submit", { cancelable: true }));
  }

  /** Answer the three requests an edit makes: the POST, the polls, and the
   *  library refresh the result triggers. `documents` is what each poll
   *  returns, with the last one repeating. */
  function mockEditFlow(documents) {
    let polls = 0;
    fetchMock.mockImplementation(async (url) => {
      if (url === "/api/jobs/1/edit") return jsonResponse({ job_id: "edit-1" }, true, 202);
      if (url === "/api/jobs/edit-1") {
        const document = documents[Math.min(polls, documents.length - 1)];
        polls += 1;
        return jsonResponse(document);
      }
      if (url.startsWith("/api/jobs?")) return jsonResponse([]);
      return jsonResponse({ error: `unexpected request to ${url}` }, false, 500);
    });
  }

  const EDITED = {
    id: "edit-1",
    filename: "holiday-crop.mp4",
    status: "done",
    output_url: "http://minio/holiday-crop.mp4",
  };

  /** The operations the panel actually sent, in a stable order -- the array's
   *  order means nothing to the worker, so nothing here should depend on it. */
  function sentOperations() {
    const call = fetchMock.mock.calls.find(([url]) => url.endsWith("/edit"));
    expect(call, "no edit request was sent").toBeTruthy();
    const [url, init] = call;
    expect(url).toBe("/api/jobs/1/edit");
    expect(init.method).toBe("POST");
    const { operations } = JSON.parse(init.body);
    return [...operations].sort((a, b) => a.operation.localeCompare(b.operation));
  }

  it("opens from a finished library entry, on that job", async () => {
    const el = await loadApp();
    await openEditor(el);

    expect(el.viewEdit.hidden).toBe(false);
    expect(el.editSource.textContent).toBe("holiday.mp4");
    expect(el.editPlayer.querySelector("video").getAttribute("src")).toBe(SOURCE.output_url);
    expect(FakePlyr.created).toHaveLength(1);
  });

  it("offers no Edit for a job that has not finished", async () => {
    const el = await loadApp();
    await openLibraryWith(el, [{ id: "2", filename: "recap.mov", status: "processing" }]);

    expect(el.libraryGrid.querySelector(".card-edit")).toBeNull();
  });

  it("opens from the upload card once its job is done, and not before", async () => {
    const el = await loadApp();
    fetchMock
      .mockResolvedValueOnce(jsonResponse({ job_id: "job-1" }))
      .mockResolvedValueOnce(jsonResponse({ id: "job-1", status: "processing" }))
      .mockResolvedValue(
        jsonResponse({ ...SOURCE, id: "job-1", filename: "uploaded.mp4" }),
      );

    await uploadFile(el);
    expect(el.jobEdit.hidden).toBe(true);

    await vi.advanceTimersByTimeAsync(4000);

    expect(el.jobEdit.hidden).toBe(false);
    el.jobEdit.dispatchEvent(new Event("click"));
    expect(el.viewEdit.hidden).toBe(false);
    expect(el.editSource.textContent).toBe("uploaded.mp4");
  });

  it("disables the sections whose components have not landed", async () => {
    const el = await loadApp();
    await openEditor(el);

    expect(el.editCrop.disabled).toBe(true);
    expect(el.editClip.disabled).toBe(true);
    // Visitors see this, so it says what they can expect -- not which of
    // the team's tracks owns the missing component.
    expect(el.editCropMount.textContent).toContain("next update");
    expect(el.editClipMount.textContent).toContain("next update");
    expect(el.editCropMount.textContent).not.toMatch(/Track [A-E]/);
    expect(el.editClipMount.textContent).not.toMatch(/Track [A-E]/);
    // The three the panel owns are always usable.
    expect(el.editDownscale.disabled).toBe(false);
    expect(el.editUpscale.disabled).toBe(false);
    expect(el.editConvert.disabled).toBe(false);
  });

  it("mounts crop and clip against the video, and sends what they report", async () => {
    const crop = fakeComponent();
    const clip = fakeComponent();
    window.mountCropBox = crop.mount.bind(crop);
    window.mountClipScrubber = clip.mount.bind(clip);
    const el = await loadApp();
    await openEditor(el);

    const video = el.editPlayer.querySelector("video");
    expect(crop.calls[0].video).toBe(video);
    expect(clip.calls[0].video).toBe(video);
    expect(el.editCrop.disabled).toBe(false);

    el.editCrop.checked = true;
    el.editCrop.dispatchEvent(new Event("change"));
    el.editClip.checked = true;
    el.editClip.dispatchEvent(new Event("change"));
    // Ticked but with nothing selected yet: there is no rectangle or range to
    // send, and a request without them is a 422.
    expect(el.editProcess.disabled).toBe(true);

    crop.report({ x: 0, y: 140, w: 1080, h: 1080 });
    clip.report({ start: 5, end: 12.5 });
    expect(el.editProcess.disabled).toBe(false);

    submit(el);

    expect(sentOperations()).toEqual([
      { operation: "clip", params: { start: 5, end: 12.5 } },
      { operation: "crop", params: { x: 0, y: 140, w: 1080, h: 1080 } },
    ]);
  });

  it("cannot be made to send downscale and upscale together", async () => {
    const el = await loadApp();
    await openEditor(el);

    el.editDownscale.checked = true;
    el.editDownscale.dispatchEvent(new Event("change"));
    expect(el.editUpscale.disabled).toBe(true);

    // Even if the checkbox is forced, ticking it closes the other one -- the
    // worker answers this combination with a 422, so the panel must not be
    // able to build it.
    el.editUpscale.checked = true;
    el.editUpscale.dispatchEvent(new Event("change"));
    expect(el.editDownscale.checked).toBe(false);

    submit(el);

    expect(sentOperations()).toEqual([
      { operation: "upscale", params: { height: 1080 } },
    ]);
  });

  it("sends the operations the panel owns with the chosen values", async () => {
    const el = await loadApp();
    await openEditor(el);

    el.editDownscale.checked = true;
    el.editDownscale.dispatchEvent(new Event("change"));
    el.editDownscaleHeight.value = "360";
    el.editConvert.checked = true;
    el.editConvert.dispatchEvent(new Event("change"));
    el.editConvertFormat.value = "mp3";

    submit(el);

    expect(sentOperations()).toEqual([
      { operation: "convert", params: { format: "mp3" } },
      { operation: "downscale", params: { height: 360 } },
    ]);
  });

  it("says what still has to be done before Process will send anything", async () => {
    const el = await loadApp();
    await openEditor(el);

    expect(el.editProcess.disabled).toBe(true);
    expect(el.editHint.textContent).toContain("Check an operation");

    el.editConvert.checked = true;
    el.editConvert.dispatchEvent(new Event("change"));

    expect(el.editProcess.disabled).toBe(false);
    expect(el.editHint.textContent).toBe("1 operation in one pass.");
  });

  it("follows the new job and offers the result", async () => {
    const el = await loadApp();
    await openEditor(el);
    mockEditFlow([{ id: "edit-1", status: "processing" }, EDITED]);

    el.editConvert.checked = true;
    el.editConvert.dispatchEvent(new Event("change"));
    submit(el);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(4000);

    expect(el.editResult.hidden).toBe(false);
    expect(el.editResultName.textContent).toBe(EDITED.filename);
    expect(el.editResultDownload.getAttribute("href")).toBe(EDITED.output_url);
    expect(el.editResultDownload.getAttribute("download")).toBe(EDITED.filename);
    expect(el.editResultPlayer.querySelector("video")).not.toBeNull();
    expect(el.editProgress.hidden).toBe(true);
  });

  it("warns that a converted result may not play inline", async () => {
    const el = await loadApp();
    await openEditor(el);
    mockEditFlow([
      { id: "edit-1", filename: "holiday.mkv", status: "done", output_url: "http://minio/holiday.mkv" },
    ]);

    el.editConvert.checked = true;
    el.editConvert.dispatchEvent(new Event("change"));
    submit(el);
    await vi.advanceTimersByTimeAsync(0);

    expect(el.editResultNote.hidden).toBe(false);
    expect(el.editResultNote.textContent).toContain("Download");
  });

  it("passes the API's own message back when the edit is refused", async () => {
    const el = await loadApp();
    await openEditor(el);
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: [{ msg: "downscale and upscale cannot be combined" }] }, false, 422),
    );

    el.editConvert.checked = true;
    el.editConvert.dispatchEvent(new Event("change"));
    submit(el);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.editStatus.textContent).toContain("downscale and upscale cannot be combined");
    expect(el.editStatus.textContent).toContain("422");
  });

  it("says which status it got when the endpoint is not there yet", async () => {
    const el = await loadApp();
    await openEditor(el);
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "Not Found" }, false, 404));

    el.editConvert.checked = true;
    el.editConvert.dispatchEvent(new Event("change"));
    submit(el);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.editStatus.textContent).toBe("Could not start the edit: Not Found (HTTP 404)");
    // The panel is still usable, so a second attempt is not blocked.
    expect(el.editProcess.disabled).toBe(false);
  });

  it("returns to the sign-in form if the session expired mid-edit", async () => {
    const el = await loadApp();
    await openEditor(el);
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "not authenticated" }, false, 401));

    el.editConvert.checked = true;
    el.editConvert.dispatchEvent(new Event("change"));
    submit(el);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(0);

    expect(el.auth.hidden).toBe(false);
    expect(el.authStatus.textContent).toContain("session expired");
  });

  it("stops following the edit, and tears the session down, on the way out", async () => {
    const crop = fakeComponent();
    window.mountCropBox = crop.mount.bind(crop);
    const el = await loadApp();
    await openEditor(el);
    mockEditFlow([{ id: "edit-1", status: "processing" }]);

    el.editConvert.checked = true;
    el.editConvert.dispatchEvent(new Event("change"));
    submit(el);
    await vi.advanceTimersByTimeAsync(4000);
    // Only the polls: going back also refetches the library, which is a
    // different request and not the thing being asserted here.
    const editsPolled = () =>
      fetchMock.mock.calls.filter(([url]) => url === "/api/jobs/edit-1").length;
    const pollsWhileOpen = editsPolled();
    expect(pollsWhileOpen).toBeGreaterThan(1);

    el.editBack.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(20000);

    expect(editsPolled()).toBe(pollsWhileOpen);
    expect(crop.cleanup).toHaveBeenCalled();
    expect(el.editPlayer.querySelector("video")).toBeNull();
    expect(FakePlyr.created[0].destroyed).toBe(true);
    expect(el.viewLibrary.hidden).toBe(false);
  });
});

describe("public intent replay", () => {
  it("replays an upload after a lost response with identical file and key, then uses a fresh key for a new upload", async () => {
    const el = await loadApp();
    fetchMock.mockRejectedValueOnce(new Error("response lost"))
      .mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValue(jsonResponse({ status: "done" }));
    await uploadFile(el);
    const posts = fetchMock.mock.calls.filter(([url]) => url === "/api/upload");
    expect(posts).toHaveLength(2);
    expect(posts[0][1].headers["Idempotency-Key"]).toBe(posts[1][1].headers["Idempotency-Key"]);
    expect(posts[0][1].body.get("file")).toBe(posts[1][1].body.get("file"));
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "two" }));
    await uploadFile(el);
    const newPost = fetchMock.mock.calls.filter(([url]) => url === "/api/upload").at(-1);
    expect(newPost[1].headers["Idempotency-Key"]).not.toBe(posts[0][1].headers["Idempotency-Key"]);
  });

  it("retains an unresolved upload key for the retry button after bounded transport failures", async () => {
    const el = await loadApp();
    fetchMock.mockRejectedValue(new Error("lost"));
    await uploadFile(el);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const original = fetchMock.mock.calls[0][1];
    expect(el.jobActions.hidden).toBe(false);
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValue(jsonResponse({ status: "queued", submission_status: "pending" }));
    el.jobRetry.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    const replay = fetchMock.mock.calls[2][1];
    expect(replay.headers["Idempotency-Key"]).toBe(original.headers["Idempotency-Key"]);
    expect(replay.body.get("file")).toBe(original.body.get("file"));
    expect(el.status.textContent).toContain("Waiting for Processing");
  });

  it("keeps a retry intent through 503 and creates a new one only after confirmed acceptance", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValueOnce(jsonResponse({ status: "failed" }));
    await uploadFile(el);
    fetchMock.mockClear();
    fetchMock.mockResolvedValue(jsonResponse({ error: "temporarily unavailable" }, false, 503));
    el.jobRetry.dispatchEvent(new Event("click"));
    el.jobRetry.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const key = fetchMock.mock.calls[0][1].headers["Idempotency-Key"];
    expect(fetchMock.mock.calls[1][1].headers["Idempotency-Key"]).toBe(key);
    expect(el.status.textContent).toContain("temporarily unavailable");
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValueOnce(jsonResponse({ status: "failed" }));
    el.jobRetry.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock.mock.calls[2][1].headers["Idempotency-Key"]).toBe(key);
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValueOnce(jsonResponse({ status: "queued" }));
    el.jobRetry.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock.mock.calls[4][1].headers["Idempotency-Key"]).not.toBe(key);
    expect(fetchMock.mock.calls.every(([url]) => url !== "/api/upload")).toBe(true);
  });

  it.each([401, 409, 404])("handles stored retry rejection %s", async (code) => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValueOnce(jsonResponse({ status: "failed" }));
    await uploadFile(el);
    fetchMock.mockResolvedValueOnce(jsonResponse({ error: "rejected" }, false, code));
    el.jobRetry.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    expect(el.jobRetry.disabled).toBe(false);
    if (code === 401) expect(el.authStatus.textContent).toContain("session expired");
    else expect(el.status.textContent).toContain("Could not retry");
  });

  it("allows manual replay after a lost stored-retry response without uploading", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValueOnce(jsonResponse({ status: "failed" }));
    await uploadFile(el);
    fetchMock.mockClear();
    fetchMock.mockRejectedValue(new Error("lost"));
    el.jobRetry.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    const key = fetchMock.mock.calls[0][1].headers["Idempotency-Key"];
    expect(el.status.textContent).toContain("uncertain");
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValueOnce(jsonResponse({ status: "queued" }));
    el.jobRetry.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock.mock.calls[2][1].headers["Idempotency-Key"]).toBe(key);
    expect(fetchMock.mock.calls[2][1].body).toBeUndefined();
  });

  it("offers stored retry from the library after page load without any remembered file", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: "one", filename: "old.mp4", status: "failed" }]));
    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    fetchMock.mockClear();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValueOnce(jsonResponse({ status: "queued" }));
    el.libraryGrid.querySelector(".card-retry").dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/jobs/one/retry");
    expect(el.jobFilename.textContent).toBe("old.mp4");
    expect(el.viewUpload.hidden).toBe(false);
  });

  it("reports a status outage and resumes checking without projecting an invented state", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValueOnce(jsonResponse({ error: "unavailable" }, false, 503))
      .mockResolvedValueOnce(jsonResponse({ status: "done" }));
    await uploadFile(el);
    expect(el.status.textContent).toContain("temporarily unavailable");
    expect(el.jobBadge.textContent).toBe("Queued");
    await vi.advanceTimersByTimeAsync(2000);
    expect(el.status.textContent).toBe("Processing complete.");
  });

  it("does not treat a missing asset as a queued job", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "one" }))
      .mockResolvedValueOnce(jsonResponse({ error: "absent" }, false, 404));
    await uploadFile(el);
    expect(el.status.textContent).toContain("Status request failed: 404");
    await vi.advanceTimersByTimeAsync(6000);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("replays immutable edits with a stable key and treats the next confirmed user edit as new", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: "source", filename: "old.mp4", status: "done" }]));
    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
    el.libraryGrid.querySelector(".card-edit").dispatchEvent(new Event("click"));
    el.editConvert.checked = true;
    el.editConvert.dispatchEvent(new Event("change"));
    fetchMock.mockClear();
    fetchMock.mockRejectedValue(new Error("lost"));
    el.editForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.advanceTimersByTimeAsync(0);
    const original = fetchMock.mock.calls[0][1];
    expect(fetchMock.mock.calls[1][1].body).toBe(original.body);
    expect(fetchMock.mock.calls[1][1].headers["Idempotency-Key"]).toBe(original.headers["Idempotency-Key"]);
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "derived" }))
      .mockResolvedValueOnce(jsonResponse({ status: "failed" }));
    el.editForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock.mock.calls[2][1].headers["Idempotency-Key"]).toBe(original.headers["Idempotency-Key"]);
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "derived2" }))
      .mockResolvedValueOnce(jsonResponse({ status: "queued" }));
    el.editForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock.mock.calls[4][1].headers["Idempotency-Key"]).not.toBe(original.headers["Idempotency-Key"]);
  });
});

describe("client review regressions", () => {
  async function login(el, id = "u-1") {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id, email: `${id}@example.test`, role: "user" }));
    el.authEmail.value = `${id}@example.test`;
    el.authPassword.value = "fixture-password";
    el.authForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.advanceTimersByTimeAsync(0);
    expect(el.auth.hidden).toBe(true);
  }

  async function libraryJob(el, status = "failed") {
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: "A", filename: "A.mp4", status }]));
    el.navLibrary.dispatchEvent(new Event("click"));
    await vi.advanceTimersByTimeAsync(0);
  }

  function submitEdit(el) {
    el.editForm.dispatchEvent(new Event("submit", { cancelable: true }));
  }

  async function openEdit(el) {
    await libraryJob(el, "done");
    el.libraryGrid.querySelector(".card-edit").click();
    el.editConvert.checked = true;
    el.editConvert.dispatchEvent(new Event("change"));
  }

  it.each([202, 401, 503, "lost"])("fences a deferred retry %s against a newer upload and its Delete target", async (status) => {
    const el = await loadApp();
    await libraryJob(el);
    let resolveRetry;
    let rejectRetry;
    const delayed = new Promise((resolve, reject) => { resolveRetry = resolve; rejectRetry = reject; });
    // For 503/lost both bounded attempts remain held until B owns the card.
    fetchMock.mockReturnValueOnce(delayed).mockReturnValueOnce(delayed);
    el.libraryGrid.querySelector(".card-retry").click();
    // Remove the unused second mock: the next request is B's upload.
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (url, init) => {
      if (url === "/api/upload") return jsonResponse({ job_id: "B" });
      if (url === "/api/jobs/A/retry") return delayed;
      if (init?.method === "DELETE") return jsonResponse({});
      return jsonResponse({ id: "B", filename: "B.mp4", status: "processing" });
    });
    await uploadFile(el, fileNamed("B.mp4"));
    expect(el.jobFilename.textContent).toBe("B.mp4");
    if (status === "lost") rejectRetry(new Error("late loss"));
    else resolveRetry(jsonResponse({ job_id: "A" }, status === 202, status));
    await vi.advanceTimersByTimeAsync(0);
    expect(el.auth.hidden).toBe(true);
    expect(el.jobFilename.textContent).toBe("B.mp4");
    expect(el.jobBadge.textContent).toBe("Processing");
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/jobs/A")).toBe(false);
    const before = fetchMock.mock.calls.filter(([url]) => url === "/api/jobs/B").length;
    await vi.advanceTimersByTimeAsync(2000);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/jobs/B")).toHaveLength(before + 1);
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    el.jobDelete.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(confirm).toHaveBeenCalledWith('Delete "B.mp4"? This cannot be undone.');
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE").map(([url]) => url)).toEqual(["/api/jobs/B"]);
  });

  it("does not clear a newer unresolved upload when an old retry reply arrives", async () => {
    const el = await loadApp();
    await libraryJob(el);
    let release;
    fetchMock.mockReturnValueOnce(new Promise((resolve) => { release = resolve; }));
    el.libraryGrid.querySelector(".card-retry").click();
    fetchMock.mockRejectedValue(new Error("B response lost"));
    const file = fileNamed("B.mp4");
    await uploadFile(el, file);
    const original = fetchMock.mock.calls.filter(([url]) => url === "/api/upload")[0][1];
    release(jsonResponse({ job_id: "A" }));
    await vi.advanceTimersByTimeAsync(0);
    expect(el.jobFilename.textContent).toBe("B.mp4");
    expect(el.status.textContent).toContain("B response lost");
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "B" }))
      .mockResolvedValueOnce(jsonResponse({ id: "B", status: "done" }));
    el.jobRetry.click();
    await vi.advanceTimersByTimeAsync(0);
    const replay = fetchMock.mock.calls.filter(([url]) => url === "/api/upload").at(-1)[1];
    expect(replay.headers["Idempotency-Key"]).toBe(original.headers["Idempotency-Key"]);
    expect(replay.body.get("file")).toBe(file);
  });

  it.each(["upload", "retry", "edit"])("resumes lost %s → 401 → same-owner login with original content/key and later fresh keys", async (operation) => {
    const el = await loadApp();
    const file = fileNamed("original.mp4");
    if (operation === "retry") await libraryJob(el);
    if (operation === "edit") await openEdit(el);
    fetchMock.mockRejectedValueOnce(new Error("acknowledgement lost"))
      .mockResolvedValueOnce(jsonResponse({}, false, 401));
    if (operation === "upload") await uploadFile(el, file);
    if (operation === "retry") el.libraryGrid.querySelector(".card-retry").click();
    if (operation === "edit") submitEdit(el);
    await vi.advanceTimersByTimeAsync(0);
    expect(el.auth.hidden).toBe(false);
    const url = operation === "upload" ? "/api/upload" : `/api/jobs/A/${operation}`;
    const requests = () => fetchMock.mock.calls.filter(([path]) => path === url);
    const original = requests()[0][1];
    expect(requests()).toHaveLength(2);
    expect(requests()[1][1].headers["Idempotency-Key"]).toBe(original.headers["Idempotency-Key"]);
    await login(el);
    if (operation === "edit") await openEdit(el);
    if (operation !== "edit") expect(el.jobActions.hidden).toBe(false);
    const accept = () => fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "A" }))
      .mockResolvedValueOnce(jsonResponse({ id: "A", filename: "original.mp4", status: "failed" }));
    accept();
    if (operation === "edit") submitEdit(el);
    else el.jobRetry.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(requests()).toHaveLength(3);
    const resumed = requests()[2][1];
    expect(resumed.headers["Idempotency-Key"]).toBe(original.headers["Idempotency-Key"]);
    if (operation === "upload") expect(resumed.body.get("file")).toBe(file);
    else expect(resumed.body).toBe(original.body); // exact immutable edit JSON / bodyless retry
    accept();
    if (operation === "upload") await uploadFile(el, file);
    if (operation === "retry") el.jobRetry.click();
    if (operation === "edit") submitEdit(el);
    await vi.advanceTimersByTimeAsync(0);
    expect(requests()).toHaveLength(4);
    expect(requests()[3][1].headers["Idempotency-Key"]).not.toBe(original.headers["Idempotency-Key"]);
    if (operation !== "upload") expect(fetchMock.mock.calls.some(([path]) => path === "/api/upload")).toBe(false);
  });

  it.each(["upload", "retry", "edit"])("isolates unresolved %s across accounts and preserves it for the original owner", async (operation) => {
    const el = await loadApp();
    const file = fileNamed("private-original.mp4");
    if (operation === "retry") await libraryJob(el);
    if (operation === "edit") await openEdit(el);
    fetchMock.mockRejectedValueOnce(new Error("ack lost"))
      .mockResolvedValueOnce(jsonResponse({}, false, 401));
    if (operation === "upload") await uploadFile(el, file);
    if (operation === "retry") el.libraryGrid.querySelector(".card-retry").click();
    if (operation === "edit") submitEdit(el);
    await vi.advanceTimersByTimeAsync(0);
    const url = operation === "upload" ? "/api/upload" : `/api/jobs/A/${operation}`;
    const requests = () => fetchMock.mock.calls.filter(([path]) => path === url);
    const original = requests()[0][1];
    await login(el, "other-owner");
    expect(el.activeJob.hidden).toBe(true);
    el.jobRetry.click(); // no hidden original-owner replay
    await vi.advanceTimersByTimeAsync(0);
    expect(requests()).toHaveLength(2);
    if (operation === "retry") await libraryJob(el);
    if (operation === "edit") await openEdit(el);
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "A" }))
      .mockResolvedValueOnce(jsonResponse({ id: "A", filename: "other.mp4", status: "failed" }));
    if (operation === "upload") await uploadFile(el, file);
    if (operation === "retry") el.libraryGrid.querySelector(".card-retry").click();
    if (operation === "edit") submitEdit(el);
    await vi.advanceTimersByTimeAsync(0);
    expect(requests()[2][1].headers["Idempotency-Key"]).not.toBe(original.headers["Idempotency-Key"]);
    fetchMock.mockResolvedValueOnce(jsonResponse({}));
    el.logout.click();
    await vi.advanceTimersByTimeAsync(0);
    await login(el);
    if (operation === "edit") await openEdit(el);
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "A" }))
      .mockResolvedValueOnce(jsonResponse({ id: "A", status: "queued" }));
    if (operation === "edit") submitEdit(el);
    else el.jobRetry.click();
    await vi.advanceTimersByTimeAsync(0);
    expect(requests()).toHaveLength(4);
    const resumed = requests()[3][1];
    expect(resumed.headers["Idempotency-Key"]).toBe(original.headers["Idempotency-Key"]);
    if (operation === "upload") expect(resumed.body.get("file")).toBe(file);
    else expect(resumed.body).toBe(original.body);
  });

  it.each(["upload", "retry", "edit"])("fences an in-flight %s across logout/login and does not replay it under a new session", async (operation) => {
    const el = await loadApp();
    if (operation === "retry") await libraryJob(el);
    if (operation === "edit") await openEdit(el);
    let reject;
    fetchMock.mockReturnValueOnce(new Promise((_, fail) => { reject = fail; }));
    if (operation === "upload") await uploadFile(el);
    if (operation === "retry") el.libraryGrid.querySelector(".card-retry").click();
    if (operation === "edit") submitEdit(el);
    fetchMock.mockResolvedValueOnce(jsonResponse({}));
    el.logout.click();
    await vi.advanceTimersByTimeAsync(0);
    await login(el, "other-owner");
    const count = fetchMock.mock.calls.length;
    reject(new Error("old session lost response"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock).toHaveBeenCalledTimes(count);
    expect(el.activeJob.hidden).toBe(true);
    expect(el.auth.hidden).toBe(true);
    expect(el.fileInput.disabled).toBe(false);
  });
});

describe("replaced mutation controls", () => {
  it("releases an abandoned upload and ignores its deferred acceptance after a library retry", async () => {
    const el = await loadApp();
    let releaseUpload;
    fetchMock.mockReturnValueOnce(new Promise((resolve) => { releaseUpload = resolve; }));
    await uploadFile(el, fileNamed("old-upload.mp4"));
    expect(el.fileInput.disabled).toBe(true);
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: "A", filename: "A.mp4", status: "failed" }]));
    el.navLibrary.click();
    await vi.advanceTimersByTimeAsync(0);
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "A" }))
      .mockResolvedValueOnce(jsonResponse({ id: "A", status: "processing" }));
    el.libraryGrid.querySelector(".card-retry").click();
    await vi.advanceTimersByTimeAsync(0);
    expect(el.fileInput.disabled).toBe(false);
    releaseUpload(jsonResponse({ job_id: "old-upload" }));
    await vi.advanceTimersByTimeAsync(0);
    expect(el.jobFilename.textContent).toBe("A.mp4");
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/jobs/old-upload")).toBe(false);
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "new-upload" }))
      .mockResolvedValueOnce(jsonResponse({ status: "done" }));
    await uploadFile(el, fileNamed("new-upload.mp4"));
    expect(el.jobFilename.textContent).toBe("new-upload.mp4");
    expect(el.fileInput.disabled).toBe(false);
  });

  it("does not release a newer retry's controls when the replaced retry finishes", async () => {
    const el = await loadApp();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "A" }))
      .mockResolvedValueOnce(jsonResponse({ id: "A", filename: "A.mp4", status: "failed" }));
    await uploadFile(el, fileNamed("A.mp4"));
    let releaseA;
    fetchMock.mockReturnValueOnce(new Promise((resolve) => { releaseA = resolve; }));
    el.jobRetry.click();
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "B" }))
      .mockResolvedValueOnce(jsonResponse({ id: "B", filename: "B.mp4", status: "failed" }));
    await uploadFile(el, fileNamed("B.mp4"));
    let releaseB;
    fetchMock.mockReturnValueOnce(new Promise((resolve) => { releaseB = resolve; }));
    el.jobRetry.click();
    expect(el.jobRetry.disabled).toBe(true);
    releaseA(jsonResponse({ job_id: "A" }));
    await vi.advanceTimersByTimeAsync(0);
    expect(el.jobFilename.textContent).toBe("B.mp4");
    expect(el.jobRetry.disabled).toBe(true);
    fetchMock.mockResolvedValueOnce(jsonResponse({ id: "B", status: "processing" }));
    releaseB(jsonResponse({ job_id: "B" }));
    await vi.advanceTimersByTimeAsync(0);
    expect(el.jobRetry.disabled).toBe(false);
    expect(el.jobBadge.textContent).toBe("Processing");
  });

  it("keeps a newer editor usable and ignores the replaced edit's deferred acknowledgement", async () => {
    const el = await loadApp();
    const open = async (id) => {
      fetchMock.mockResolvedValueOnce(jsonResponse([{ id, filename: `${id}.mp4`, status: "done" }]));
      el.navLibrary.click();
      await vi.advanceTimersByTimeAsync(0);
      el.libraryGrid.querySelector(".card-edit").click();
      el.editConvert.checked = true;
      el.editConvert.dispatchEvent(new Event("change"));
    };
    await open("A");
    let releaseA;
    fetchMock.mockReturnValueOnce(new Promise((resolve) => { releaseA = resolve; }));
    el.editForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await open("B");
    fetchMock.mockResolvedValueOnce(jsonResponse({ job_id: "derived-B" }))
      .mockResolvedValueOnce(jsonResponse({ status: "failed" }));
    el.editForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/jobs/B/edit")).toBe(true);
    releaseA(jsonResponse({ job_id: "derived-A" }));
    await vi.advanceTimersByTimeAsync(0);
    expect(el.editSource.textContent).toBe("B.mp4");
    expect(el.editStatus.textContent).toContain("The edit failed");
    expect(fetchMock.mock.calls.some(([url]) => url === "/api/jobs/derived-A")).toBe(false);
    expect(el.editProcess.disabled).toBe(false);
  });
});

describe("list errors and account switching (default /api/media routes)", () => {
  const flush = () => vi.advanceTimersByTimeAsync(0);
  const A_JOB = {
    id: "A1",
    filename: "A-private.mp4",
    status: "done",
    output_url: "https://storage.example.test/a?signature=FAKE",
  };

  async function signInAs(el, id, role = "user") {
    fetchMock.mockResolvedValueOnce(jsonResponse({ id, email: `${id}@example.test`, role }));
    el.authEmail.value = `${id}@example.test`;
    el.authPassword.value = "fixture-password";
    el.authForm.dispatchEvent(new Event("submit", { cancelable: true }));
    await flush();
  }

  async function signOut(el) {
    fetchMock.mockResolvedValueOnce(jsonResponse({}, true, 204));
    el.logout.click();
    await flush();
  }

  const deferred = () => {
    let resolve;
    const promise = new Promise((r) => { resolve = r; });
    return { promise, resolve };
  };

  it("uses the Media base for the list and distinguishes failure from an empty list", async () => {
    const el = await loadApp({ legacy: false });
    fetchMock.mockResolvedValueOnce(jsonResponse({}, false, 503));
    el.navLibrary.click();
    await flush();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/media/jobs?limit=12&offset=0");
    expect(el.libraryEmpty.hidden).toBe(true);
    expect(el.libraryStatus.textContent).toContain("Could not load");

    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    el.libraryRetry.click();
    await flush();
    expect(el.libraryStatus.hidden).toBe(true);
    expect(el.libraryRetry.hidden).toBe(true);
    expect(el.libraryEmpty.hidden).toBe(false);
  });

  it("treats malformed list JSON as a load error and recovers on retry", async () => {
    const el = await loadApp({ legacy: false });
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: async () => { throw new Error("bad"); } });
    el.navLibrary.click();
    await flush();
    expect(el.libraryEmpty.hidden).toBe(true);
    expect(el.libraryRetry.hidden).toBe(false);

    fetchMock.mockResolvedValueOnce(jsonResponse([A_JOB]));
    el.libraryRetry.click();
    await flush();
    expect(el.libraryGrid.textContent).toContain("A-private.mp4");
    expect(el.libraryStatus.hidden).toBe(true);
  });

  it("shows an admin error, then recovers on retry", async () => {
    const el = await loadApp({ legacy: false, role: "operator" });
    fetchMock.mockRejectedValueOnce(new Error("down"));
    el.navAdmin.click();
    await flush();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/media/admin/jobs?limit=12&offset=0");
    expect(el.adminEmpty.hidden).toBe(true);
    expect(el.adminStatus.textContent).toContain("Could not load");

    fetchMock.mockResolvedValueOnce(jsonResponse([]));
    el.adminRetry.click();
    await flush();
    expect(el.adminStatus.hidden).toBe(true);
    expect(el.adminEmpty.hidden).toBe(false);
  });

  it("shows none of owner A's library while owner B's list is pending", async () => {
    const el = await loadApp({ legacy: false });
    fetchMock.mockResolvedValueOnce(jsonResponse([A_JOB]));
    el.navLibrary.click();
    await flush();
    expect(el.libraryGrid.querySelector(".playable")).toBeTruthy();

    await signOut(el);
    await signInAs(el, "B");
    fetchMock.mockReturnValueOnce(new Promise(() => {}));
    el.navLibrary.click();
    await flush();

    expect(el.libraryGrid.textContent).not.toContain("A-private.mp4");
    expect(el.libraryGrid.querySelector(".playable")).toBeNull();
    expect(document.body.textContent).not.toContain("signature=FAKE");
  });

  it("ignores owner A's late list response, including delayed JSON parsing, after B has loaded", async () => {
    const el = await loadApp({ legacy: false });
    const body = deferred();
    fetchMock.mockResolvedValueOnce({ ok: true, status: 200, json: () => body.promise });
    el.navLibrary.click();
    await flush();

    await signOut(el);
    await signInAs(el, "B");
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: "B1", filename: "B.mp4", status: "queued" }]));
    el.navLibrary.click();
    await flush();
    expect(el.libraryGrid.textContent).toContain("B.mp4");

    body.resolve([A_JOB]);
    await flush();
    expect(el.libraryGrid.textContent).toContain("B.mp4");
    expect(el.libraryGrid.textContent).not.toContain("A-private.mp4");
  });

  it("does not let owner A's late 401 or failure sign B out or replace B's list", async () => {
    const el = await loadApp({ legacy: false });
    const late401 = deferred();
    const lateFail = deferred();
    fetchMock.mockReturnValueOnce(late401.promise);
    el.navLibrary.click();
    await flush();
    await signOut(el);
    await signInAs(el, "B");
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: "B1", filename: "B.mp4", status: "queued" }]));
    el.navLibrary.click();
    await flush();

    late401.resolve(jsonResponse({}, false, 401));
    await flush();
    expect(el.auth.hidden).toBe(true);
    expect(el.libraryGrid.textContent).toContain("B.mp4");

    fetchMock.mockReturnValueOnce(lateFail.promise);
    el.libraryNext.disabled = false;
    el.libraryNext.click();
    await flush();
    await signOut(el);
    await signInAs(el, "C");
    lateFail.resolve(jsonResponse({}, false, 500));
    await flush();
    expect(el.libraryStatus.hidden).toBe(true);
    expect(el.libraryRetry.hidden).toBe(true);
  });

  it("leaves no admin rows from operator A for ordinary user B", async () => {
    const el = await loadApp({ legacy: false, role: "operator" });
    fetchMock.mockResolvedValueOnce(jsonResponse([A_JOB]));
    el.navAdmin.click();
    await flush();
    expect(el.adminTbody.textContent).toContain("A-private.mp4");

    await signOut(el);
    await signInAs(el, "B", "user");
    expect(el.adminTbody.textContent).not.toContain("A-private.mp4");
    expect(el.adminTbody.querySelector("video, audio, [data-hls]")).toBeNull();
    expect(el.navAdmin.hidden).toBe(true);
  });

  it("leaves no editor result or download capability for the next owner", async () => {
    const el = await loadApp({ legacy: false });
    const SRC = { id: "S", filename: "A-src.mp4", status: "done", output_url: "https://s.example.test/src?sig=FAKE" };
    fetchMock.mockResolvedValueOnce(jsonResponse([SRC]));
    el.navLibrary.click();
    await flush();
    el.libraryGrid.querySelector(".card-edit").click();
    await flush();
    const dl = document.getElementById("edit-result-download");
    dl.href = "https://s.example.test/derived?sig=FAKE";
    dl.setAttribute("download", "A-derived.mp4");
    document.getElementById("edit-result-name").textContent = "A-derived.mp4";

    await signOut(el);
    await signInAs(el, "B");
    expect(dl.getAttribute("href")).toBeNull();
    expect(dl.getAttribute("download")).toBeNull();
    expect(document.getElementById("edit-result-name").textContent).toBe("");
    expect(document.getElementById("edit-source").textContent).toBe("");
  });

  it.each([401, 503])("ignores owner A's late delete %s after B has signed in", async (status) => {
    const el = await loadApp({ legacy: false });
    fetchMock.mockResolvedValueOnce(jsonResponse([A_JOB]));
    el.navLibrary.click();
    await flush();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const late = deferred();
    fetchMock.mockReturnValueOnce(late.promise);
    el.libraryGrid.querySelector(".card-delete").click();
    await flush();

    await signOut(el);
    await signInAs(el, "B");
    fetchMock.mockResolvedValueOnce(jsonResponse([{ id: "B1", filename: "B.mp4", status: "queued" }]));
    el.navLibrary.click();
    await flush();

    late.resolve(jsonResponse({ error: "x" }, false, status));
    await flush();
    expect(el.auth.hidden).toBe(true);
    expect(el.libraryStatus.textContent).not.toContain("Could not delete");
    expect(el.libraryGrid.textContent).toContain("B.mp4");
  });

  it("does not send owner A's reservation under B's session when hashing finishes late", async () => {
    const el = await loadApp({ legacy: false });
    const file = fileNamed("A-private.mp4");
    const read = deferred();
    file.arrayBuffer = async () => new ArrayBuffer(4);
    vi.spyOn(crypto.subtle, "digest").mockImplementation(() => read.promise);
    chooseFile(el.fileInput, file);
    el.fileInput.dispatchEvent(new Event("change"));
    await flush();

    await signOut(el);
    await signInAs(el, "B");
    const count = fetchMock.mock.calls.length;
    read.resolve(new ArrayBuffer(32));
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(count);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/uploads/reservations"))).toBe(false);
    expect(el.activeJob.hidden).toBe(true);
  });
});
