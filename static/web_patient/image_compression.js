(function () {
  "use strict";

  var UNSUPPORTED_BROWSER_MESSAGE = "当前浏览器版本不支持安全图片处理，请升级微信或浏览器后重试";
  var scriptElement = typeof document !== "undefined" ? document.currentScript : null;
  var workerLibUrl = scriptElement && scriptElement.dataset
    ? (scriptElement.dataset.workerLibUrl || "")
    : "";

  var DEFAULT_LIMITS = Object.freeze({
    maxFiles: 12,
    maxTotalBytes: 60 * 1024 * 1024,
    maxFileBytes: 10 * 1024 * 1024,
    maxPixels: 40 * 1000 * 1000,
  });

  var COMPRESSION_POLICY = Object.freeze({
    maxWidthOrHeight: 2560,
    maxSizeMB: 1.5,
    initialQuality: 0.82,
    preserveExif: false,
  });

  var ERROR_MESSAGES = {
    invalid_image: "图片文件无效，请选择 JPG 或 PNG 图片",
    too_large: "图片大小超过限制",
    too_many_pixels: "图片分辨率过高，请选择不超过4000万像素的图片",
    timeout: "图片处理超时，请重试",
    cancelled: "图片处理已取消",
    library_unavailable: "图片处理组件加载失败，请刷新页面后重试",
    compress_failed: "图片处理失败，请重试或删除",
  };

  function createError(code, message, cause) {
    var error = new Error(message || ERROR_MESSAGES[code] || ERROR_MESSAGES.compress_failed);
    error.code = code;
    if (cause) error.cause = cause;
    return error;
  }

  function normalizeError(error, fallbackCode) {
    if (error && error.code && ERROR_MESSAGES[error.code]) return error;
    return createError(fallbackCode || "compress_failed", null, error);
  }

  function nowMs() {
    if (typeof performance !== "undefined" && performance.now) return performance.now();
    return Date.now();
  }

  function formatBytes(bytes) {
    if (bytes === undefined || bytes === null) return "";
    var units = ["B", "KB", "MB", "GB"];
    var index = 0;
    var value = bytes;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    return value.toFixed(index === 0 ? 0 : 1) + units[index];
  }

  function getNetworkInfo() {
    var connection = typeof navigator !== "undefined" && navigator.connection
      ? navigator.connection
      : null;
    if (!connection) {
      return { effectiveType: "", saveData: false, downlink: null, rtt: null };
    }
    return {
      effectiveType: connection.effectiveType || "",
      saveData: !!connection.saveData,
      downlink: typeof connection.downlink === "number" ? connection.downlink : null,
      rtt: typeof connection.rtt === "number" ? connection.rtt : null,
    };
  }

  function readBlobAsArrayBuffer(blob) {
    if (blob && typeof blob.arrayBuffer === "function") return blob.arrayBuffer();
    return new Promise(function (resolve, reject) {
      if (typeof FileReader === "undefined") {
        reject(createError("invalid_image"));
        return;
      }
      var reader = new FileReader();
      reader.onload = function () { resolve(reader.result); };
      reader.onerror = function () { reject(createError("invalid_image", null, reader.error)); };
      reader.readAsArrayBuffer(blob);
    });
  }

  function isPng(bytes) {
    var signature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
    if (bytes.length < signature.length) return false;
    for (var index = 0; index < signature.length; index += 1) {
      if (bytes[index] !== signature[index]) return false;
    }
    return true;
  }

  function readPngDimensions(view) {
    if (view.byteLength < 24) throw createError("invalid_image");
    if (
      view.getUint32(8, false) !== 13 ||
      view.getUint8(12) !== 0x49 ||
      view.getUint8(13) !== 0x48 ||
      view.getUint8(14) !== 0x44 ||
      view.getUint8(15) !== 0x52
    ) {
      throw createError("invalid_image");
    }
    return {
      width: view.getUint32(16, false),
      height: view.getUint32(20, false),
    };
  }

  function isJpegStart(bytes) {
    return bytes.length >= 2 && bytes[0] === 0xff && bytes[1] === 0xd8;
  }

  function isJpegStartOfFrame(marker) {
    return [
      0xc0, 0xc1, 0xc2, 0xc3,
      0xc5, 0xc6, 0xc7,
      0xc9, 0xca, 0xcb,
      0xcd, 0xce, 0xcf,
    ].indexOf(marker) !== -1;
  }

  function readJpegDimensions(view) {
    var offset = 2;
    while (offset + 3 < view.byteLength) {
      while (offset < view.byteLength && view.getUint8(offset) !== 0xff) offset += 1;
      while (offset < view.byteLength && view.getUint8(offset) === 0xff) offset += 1;
      if (offset >= view.byteLength) break;

      var marker = view.getUint8(offset);
      offset += 1;
      if (marker === 0xd8 || marker === 0x01) continue;
      if (marker === 0xd9 || marker === 0xda) break;
      if (offset + 2 > view.byteLength) break;

      var segmentLength = view.getUint16(offset, false);
      if (segmentLength < 2 || offset + segmentLength > view.byteLength) break;
      if (isJpegStartOfFrame(marker)) {
        if (segmentLength < 7 || offset + 7 > view.byteLength) break;
        return {
          height: view.getUint16(offset + 3, false),
          width: view.getUint16(offset + 5, false),
        };
      }
      offset += segmentLength;
    }
    throw createError("invalid_image");
  }

  function inspectImage(file, options) {
    var limits = Object.assign({}, DEFAULT_LIMITS, options || {});
    if (!file || !file.size || typeof file.slice !== "function") {
      return Promise.reject(createError("invalid_image"));
    }
    if (file.size > limits.maxFileBytes) {
      return Promise.reject(createError("too_large", "单张图片不能超过10MB"));
    }

    var header = file.slice(0, Math.min(file.size, 2 * 1024 * 1024));
    return readBlobAsArrayBuffer(header).then(function (buffer) {
      var bytes = new Uint8Array(buffer);
      var view = new DataView(buffer);
      var dimensions;
      var format;
      var mimeType;

      if (isPng(bytes)) {
        dimensions = readPngDimensions(view);
        format = "png";
        mimeType = "image/png";
      } else if (isJpegStart(bytes)) {
        dimensions = readJpegDimensions(view);
        format = "jpeg";
        mimeType = "image/jpeg";
      } else {
        throw createError("invalid_image");
      }

      var width = dimensions.width;
      var height = dimensions.height;
      var pixels = width * height;
      if (!width || !height || !Number.isSafeInteger(pixels)) {
        throw createError("invalid_image");
      }
      if (pixels > limits.maxPixels) {
        throw createError("too_many_pixels");
      }
      return {
        format: format,
        mimeType: mimeType,
        width: width,
        height: height,
        pixels: pixels,
      };
    }).catch(function (error) {
      throw normalizeError(error, "invalid_image");
    });
  }

  function selectionSize(item) {
    if (!item) return 0;
    if (typeof item.originalBytes === "number") return item.originalBytes;
    if (typeof item.originalSize === "number") return item.originalSize;
    if (item.sourceFile && typeof item.sourceFile.size === "number") return item.sourceFile.size;
    if (item.file && typeof item.file.size === "number") return item.file.size;
    if (typeof item.size === "number") return item.size;
    return 0;
  }

  async function validateSelection(existing, incoming, limits) {
    var policy = Object.assign({}, DEFAULT_LIMITS, limits || {});
    var current = Array.isArray(existing) ? existing : [];
    var candidates = Array.isArray(incoming) ? incoming : Array.from(incoming || []);
    var accepted = [];
    var rejected = [];
    var totalFiles = current.length;
    var totalBytes = current.reduce(function (sum, item) {
      return sum + selectionSize(item);
    }, 0);

    for (var index = 0; index < candidates.length; index += 1) {
      var file = candidates[index];
      try {
        if (totalFiles + 1 > policy.maxFiles) {
          throw createError("too_large", "单次最多选择12张图片");
        }
        if (!file || file.size > policy.maxFileBytes) {
          throw createError("too_large", "单张图片不能超过10MB");
        }
        if (totalBytes + file.size > policy.maxTotalBytes) {
          throw createError("too_large", "待上传图片原始总大小不能超过60MB");
        }
        var inspection = await inspectImage(file, policy);
        accepted.push({ file: file, inspection: inspection });
        totalFiles += 1;
        totalBytes += file.size;
      } catch (error) {
        var normalized = normalizeError(error, "invalid_image");
        rejected.push({
          file: file,
          code: normalized.code,
          message: normalized.message,
        });
      }
    }

    return {
      accepted: accepted,
      rejected: rejected,
      totalFiles: totalFiles,
      totalBytes: totalBytes,
      limits: policy,
    };
  }

  function compressOne(file, options) {
    var opts = options || {};
    var timeoutMs = typeof opts.timeoutMs === "number" ? opts.timeoutMs : 30000;
    var start = nowMs();
    var networkInfo = getNetworkInfo();
    if (typeof AbortController === "undefined") {
      return Promise.reject(createError("library_unavailable", "当前浏览器不支持安全取消图片处理，请升级后重试"));
    }
    var controller = new AbortController();
    var externalSignal = opts.signal || null;
    var timedOut = false;
    var timeoutId = null;

    function abortFromExternal() {
      if (!controller.signal.aborted) controller.abort();
    }

    if (externalSignal) {
      if (externalSignal.aborted) abortFromExternal();
      else externalSignal.addEventListener("abort", abortFromExternal, { once: true });
    }
    timeoutId = setTimeout(function () {
      timedOut = true;
      if (!controller.signal.aborted) controller.abort();
    }, timeoutMs);

    var inspectionPromise = opts.inspection
      ? Promise.resolve(opts.inspection)
      : inspectImage(file);

    return inspectionPromise.then(function (inspection) {
      if (controller.signal.aborted) {
        throw createError(timedOut ? "timeout" : "cancelled");
      }
      var library = typeof window !== "undefined" ? window.imageCompression : null;
      if (typeof library !== "function" || !workerLibUrl) {
        throw createError("library_unavailable");
      }

      var originalName = file.name || "image";
      var baseName = originalName.replace(/\.[^.]+$/, "") || "image";
      var normalizedName = baseName + (inspection.format === "jpeg" ? ".jpg" : ".png");
      var normalizedInput = new File([file], normalizedName, {
        type: inspection.mimeType,
        lastModified: file.lastModified || Date.now(),
      });

      var optionsForLibrary = {
        maxWidthOrHeight: 2560,
        maxSizeMB: 1.5,
        initialQuality: 0.82,
        useWebWorker: true,
        preserveExif: false,
        fileType: inspection.mimeType,
        onProgress: typeof opts.onProgress === "function" ? opts.onProgress : undefined,
        signal: controller.signal,
        libURL: workerLibUrl,
      };

      return library(normalizedInput, optionsForLibrary).then(function (blob) {
        if (controller.signal.aborted) {
          throw createError(timedOut ? "timeout" : "cancelled");
        }
        if (!blob || typeof blob.size !== "number" || blob.size <= 0) {
          throw createError("compress_failed");
        }
        var outputFile = blob instanceof File
          ? blob
          : new File([blob], normalizedName, {
              type: blob.type || inspection.mimeType,
              lastModified: Date.now(),
            });
        var targetBytes = COMPRESSION_POLICY.maxSizeMB * 1024 * 1024;
        if (outputFile.size > targetBytes) {
          throw createError("too_large", "图片处理后仍超过1.5MB，请重新拍摄或更换图片");
        }
        if (outputFile.size > DEFAULT_LIMITS.maxFileBytes) {
          throw createError("too_large", "处理后的图片仍超过10MB，请更换图片");
        }
        return {
          status: "ready",
          file: outputFile,
          originalBytes: file.size,
          outputBytes: outputFile.size,
          durationMs: Math.round(nowMs() - start),
          policy: Object.assign({}, COMPRESSION_POLICY),
          networkInfo: networkInfo,
        };
      });
    }).catch(function (error) {
      if (timedOut) throw createError("timeout", null, error);
      if ((externalSignal && externalSignal.aborted) || controller.signal.aborted) {
        throw createError("cancelled", null, error);
      }
      throw normalizeError(error, "compress_failed");
    }).finally(function () {
      clearTimeout(timeoutId);
      if (externalSignal) externalSignal.removeEventListener("abort", abortFromExternal);
    });
  }

  function createQueue(options) {
    if (typeof AbortController === "undefined") {
      throw createError("library_unavailable", UNSUPPORTED_BROWSER_MESSAGE);
    }
    var opts = options || {};
    var concurrency = Math.max(1, Number(opts.concurrency) || 1);
    var compressionOptions = opts.compressOptions || {};
    var onStateChange = typeof opts.onStateChange === "function" ? opts.onStateChange : null;
    var pendingIds = [];
    var tasks = new Map();
    var activeCount = 0;
    var destroyed = false;

    function notify(task) {
      if (onStateChange) onStateChange(task.id, task.state, task.error || null);
    }

    function setState(task, state, error) {
      task.state = state;
      task.error = error || null;
      notify(task);
    }

    function pump() {
      if (destroyed) return;
      while (activeCount < concurrency && pendingIds.length > 0) {
        var id = pendingIds.shift();
        var task = tasks.get(id);
        if (!task || task.state !== "queued") continue;

        var controller;
        try {
          if (typeof AbortController === "undefined") {
            throw createError("library_unavailable", UNSUPPORTED_BROWSER_MESSAGE);
          }
          controller = new AbortController();
        } catch (error) {
          var controllerError = error && error.code === "library_unavailable"
            ? error
            : createError("library_unavailable", UNSUPPORTED_BROWSER_MESSAGE, error);
          setState(task, "failed", controllerError);
          task.reject(controllerError);
          continue;
        }

        task.controller = controller;
        activeCount += 1;
        setState(task, "processing");
        var taskOptions = Object.assign({}, compressionOptions, task.options || {}, {
          inspection: task.inspection,
          onProgress: task.onProgress,
          signal: task.controller.signal,
        });

        compressOne(task.file, taskOptions).then(function (result) {
          var current = tasks.get(this.id);
          if (!current || current.state === "cancelled") return;
          current.result = result;
          setState(current, "ready");
          current.resolve(result);
        }.bind({ id: id })).catch(function (error) {
          var current = tasks.get(this.id);
          if (!current) return;
          var normalized = normalizeError(error, "compress_failed");
          if (current.state === "cancelled" || normalized.code === "cancelled") {
            normalized = createError("cancelled", null, normalized);
            setState(current, "cancelled", normalized);
          } else {
            setState(current, "failed", normalized);
          }
          current.reject(normalized);
        }.bind({ id: id })).finally(function () {
          activeCount -= 1;
          pump();
        });
      }
    }

    function enqueue(taskInput) {
      var input = taskInput || {};
      var id = input.id || (Date.now() + "-" + Math.random().toString(36).slice(2));
      if (destroyed) return Promise.reject(createError("cancelled"));
      if (!input.file) return Promise.reject(createError("invalid_image"));
      if (tasks.has(id) && ["queued", "processing"].indexOf(tasks.get(id).state) !== -1) {
        return Promise.reject(createError("compress_failed", "图片正在处理中"));
      }

      var promise = new Promise(function (resolve, reject) {
        tasks.set(id, {
          id: id,
          file: input.file,
          inspection: input.inspection || null,
          onProgress: input.onProgress || null,
          options: input.options || null,
          state: "queued",
          error: null,
          result: null,
          controller: null,
          resolve: resolve,
          reject: reject,
        });
      });
      pendingIds.push(id);
      notify(tasks.get(id));
      pump();
      return promise;
    }

    function cancel(id) {
      var task = tasks.get(id);
      if (!task || ["ready", "failed", "cancelled"].indexOf(task.state) !== -1) return false;
      var error = createError("cancelled");
      if (task.state === "queued") {
        pendingIds = pendingIds.filter(function (pendingId) { return pendingId !== id; });
        setState(task, "cancelled", error);
        task.reject(error);
        pump();
        return true;
      }
      setState(task, "cancelled", error);
      if (task.controller && !task.controller.signal.aborted) task.controller.abort();
      return true;
    }

    function hasPending() {
      return Array.from(tasks.values()).some(function (task) {
        return task.state === "queued" || task.state === "processing";
      });
    }

    function getState(id) {
      var task = tasks.get(id);
      return task ? task.state : null;
    }

    function destroy() {
      destroyed = true;
      Array.from(tasks.keys()).forEach(cancel);
    }

    return {
      enqueue: enqueue,
      cancel: cancel,
      hasPending: hasPending,
      getState: getState,
      destroy: destroy,
    };
  }

  function isQueueContract(queue) {
    if (!queue) return false;
    return ["enqueue", "cancel", "hasPending", "getState", "destroy"].every(function (method) {
      return typeof queue[method] === "function";
    });
  }

  window.LCCImageCompression = {
    API_VERSION: "clinical-readability-v2",
    DEFAULT_LIMITS: DEFAULT_LIMITS,
    COMPRESSION_POLICY: COMPRESSION_POLICY,
    formatBytes: formatBytes,
    getNetworkInfo: getNetworkInfo,
    inspectImage: inspectImage,
    validateSelection: validateSelection,
    compressOne: compressOne,
    createQueue: createQueue,
    isQueueContract: isQueueContract,
  };
})();
