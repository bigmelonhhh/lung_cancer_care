(function () {
  function formatBytes(bytes) {
    if (bytes === undefined || bytes === null) return "";
    var units = ["B", "KB", "MB", "GB"];
    var i = 0;
    var val = bytes;
    while (val >= 1024 && i < units.length - 1) {
      val = val / 1024;
      i += 1;
    }
    var fixed = i === 0 ? 0 : 1;
    return val.toFixed(fixed) + units[i];
  }

  function nowMs() {
    if (typeof performance !== "undefined" && performance.now) return performance.now();
    return Date.now();
  }

  function withTimeout(promise, ms) {
    return new Promise(function (resolve, reject) {
      var t = setTimeout(function () {
        reject(new Error("compress_timeout"));
      }, ms);
      promise.then(
        function (v) {
          clearTimeout(t);
          resolve(v);
        },
        function (e) {
          clearTimeout(t);
          reject(e);
        }
      );
    });
  }

  function getNetworkInfo() {
    var c = navigator && navigator.connection ? navigator.connection : null;
    if (!c) return { effectiveType: "", saveData: false, downlink: null, rtt: null };
    return {
      effectiveType: c.effectiveType || "",
      saveData: !!c.saveData,
      downlink: typeof c.downlink === "number" ? c.downlink : null,
      rtt: typeof c.rtt === "number" ? c.rtt : null,
    };
  }

  function chooseTargetMaxSizeMB(originalBytes, networkInfo) {
    var mb = originalBytes / (1024 * 1024);
    var base;
    if (mb <= 2) base = 0.5;
    else if (mb <= 5) base = 0.8;
    else base = 1.0;

    var eff = (networkInfo && networkInfo.effectiveType) ? String(networkInfo.effectiveType) : "";
    var saveData = networkInfo && networkInfo.saveData;

    if (saveData || eff === "slow-2g" || eff === "2g" || eff === "3g") {
      return Math.min(base, 0.5);
    }
    if (eff === "4g") {
      return base;
    }
    return base;
  }

  function chooseInitialQuality(networkInfo) {
    var eff = (networkInfo && networkInfo.effectiveType) ? String(networkInfo.effectiveType) : "";
    var saveData = networkInfo && networkInfo.saveData;
    if (saveData || eff === "slow-2g" || eff === "2g") return 0.7;
    if (eff === "3g") return 0.72;
    if (eff === "4g") return 0.75;
    return 0.75;
  }

  function shouldPreScale(width, height) {
    if (!width || !height) return false;
    return width > 1920 || height > 1080;
  }

  function preScaleToBox(file, maxW, maxH) {
    return new Promise(function (resolve, reject) {
      try {
        var reader = new FileReader();
        reader.onload = function (e) {
          var img = new Image();
          img.onload = function () {
            var w = img.width;
            var h = img.height;
            if (!shouldPreScale(w, h)) {
              resolve(file);
              return;
            }
            var ratio = Math.max(w / maxW, h / maxH);
            var tw = Math.max(1, Math.floor(w / ratio));
            var th = Math.max(1, Math.floor(h / ratio));
            var canvas = document.createElement("canvas");
            canvas.width = tw;
            canvas.height = th;
            var ctx = canvas.getContext("2d");
            ctx.drawImage(img, 0, 0, tw, th);
            canvas.toBlob(
              function (blob) {
                if (!blob) {
                  resolve(file);
                  return;
                }
                var out = new File([blob], file.name, { type: blob.type || file.type || "image/jpeg", lastModified: Date.now() });
                resolve(out);
              },
              file.type || "image/jpeg",
              0.92
            );
          };
          img.onerror = function () {
            resolve(file);
          };
          img.src = e.target.result;
        };
        reader.onerror = function () {
          resolve(file);
        };
        reader.readAsDataURL(file);
      } catch (e) {
        resolve(file);
      }
    });
  }

  function compressOne(file, opts) {
    var originalBytes = file && file.size ? file.size : 0;
    var networkInfo = getNetworkInfo();
    var maxSizeMB = chooseTargetMaxSizeMB(originalBytes, networkInfo);
    var initialQuality = chooseInitialQuality(networkInfo);

    var timeoutMs = (opts && opts.timeoutMs) ? opts.timeoutMs : 30000;
    var allowOriginal = !!(opts && opts.allowOriginal);
    var onProgress = opts && typeof opts.onProgress === "function" ? opts.onProgress : null;
    var usePreScale = opts && opts.preScaleTo1080p !== false;

    var start = nowMs();

    var run = Promise.resolve(file).then(function (f) {
      if (usePreScale) {
        return preScaleToBox(f, 1920, 1080);
      }
      return f;
    }).then(function (scaled) {
      var lib = window && window.imageCompression ? window.imageCompression : null;
      if (typeof lib !== "function") {
        return { file: scaled, usedOriginal: true, policy: { maxSizeMB: maxSizeMB, initialQuality: initialQuality }, durationMs: Math.round(nowMs() - start), networkInfo: networkInfo };
      }
      var options = {
        maxWidthOrHeight: 1920,
        maxSizeMB: maxSizeMB,
        initialQuality: initialQuality,
        useWebWorker: true,
        fileType: scaled.type || undefined,
        onProgress: onProgress || undefined,
      };
      return withTimeout(lib(scaled, options), timeoutMs).then(function (blob) {
        var outFile = blob instanceof File ? blob : new File([blob], file.name, { type: blob.type || scaled.type || file.type, lastModified: Date.now() });
        if (outFile.size > originalBytes && originalBytes > 0) {
          return { file: allowOriginal ? file : outFile, usedOriginal: allowOriginal, policy: { maxSizeMB: maxSizeMB, initialQuality: initialQuality }, durationMs: Math.round(nowMs() - start), networkInfo: networkInfo };
        }
        return { file: outFile, usedOriginal: false, policy: { maxSizeMB: maxSizeMB, initialQuality: initialQuality }, durationMs: Math.round(nowMs() - start), networkInfo: networkInfo };
      });
    });

    return run.catch(function (e) {
      if (allowOriginal) {
        return { file: file, usedOriginal: true, error: e && e.message ? e.message : "compress_failed", policy: { maxSizeMB: maxSizeMB, initialQuality: initialQuality }, durationMs: Math.round(nowMs() - start), networkInfo: networkInfo };
      }
      throw e;
    });
  }

  window.LCCImageCompression = {
    formatBytes: formatBytes,
    getNetworkInfo: getNetworkInfo,
    chooseTargetMaxSizeMB: chooseTargetMaxSizeMB,
    compressOne: compressOne,
  };
})();

