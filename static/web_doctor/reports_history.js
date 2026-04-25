(function () {
  if (window.__reportsHistoryInstalled) return;
  window.__reportsHistoryInstalled = true;

  function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== "") {
      var cookies = document.cookie.split(";");
      for (var i = 0; i < cookies.length; i += 1) {
        var cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === name + "=") {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  function showToast(message, type) {
    if (!message) return;
    var container = document.getElementById("consultation-records-toast");
    if (!container) {
      container = document.createElement("div");
      container.id = "consultation-records-toast";
      container.className =
        "fixed bottom-4 right-4 max-w-sm text-white text-sm px-3 py-2 rounded shadow-lg z-50";
      document.body.appendChild(container);
    }
    var bg = "bg-slate-800";
    if (type === "error") bg = "bg-rose-600";
    if (type === "success") bg = "bg-emerald-600";
    if (type === "info") bg = "bg-sky-600";
    container.className =
      "fixed bottom-4 right-4 max-w-sm text-white text-sm px-3 py-2 rounded shadow-lg z-50 " + bg;
    container.textContent = message;
    container.style.display = "block";
    clearTimeout(container._hideTimer);
    container._hideTimer = setTimeout(function () {
      container.style.display = "none";
    }, 4000);
  }

  function processNode(node) {
    if (!node) return;
    if (window.htmx) {
      window.htmx.process(node);
    }
    if (window.Alpine && typeof window.Alpine.initTree === "function") {
      window.Alpine.initTree(node);
    }
  }

  function replaceContent(target, html) {
    if (!target) return;
    target.innerHTML = html;
    processNode(target);
  }

  function getReportsContentTarget() {
    return document.getElementById("reports-history-content");
  }

  async function fetchText(url, options) {
    var response = await fetch(url, options || {});
    var text = await response.text();
    if (!response.ok) {
      throw new Error(text || "请求失败");
    }
    return text;
  }

  async function fetchJson(url, options) {
    var response = await fetch(url, options || {});
    var payload = await response.json().catch(function () {
      return null;
    });
    if (!response.ok || !payload) {
      var message = (payload && payload.message) || "请求失败";
      throw new Error(message);
    }
    return payload;
  }

  window.showConsultationRecordsToast = showToast;
  window.openReportsCreateModal = async function (url, type) {
    var host = document.getElementById("reports-modal-host");
    if (!host) return;
    if (host.dataset.loaded === "1") {
      document.body.dispatchEvent(
        new CustomEvent("open-add-record-modal", {
          bubbles: true,
          detail: { type: type || "" },
        })
      );
      return;
    }

    try {
      var html = await fetchText(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      host.dataset.loaded = "1";
      replaceContent(host, html);
      document.body.dispatchEvent(
        new CustomEvent("open-add-record-modal", {
          bubbles: true,
          detail: { type: type || "" },
        })
      );
    } catch (error) {
      showToast(error.message || "弹窗加载失败", "error");
    }
  };

  window.loadReportsDetail = async function (url, targetId) {
    var target = document.getElementById(targetId);
    if (!target) return false;
    try {
      var html = await fetchText(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      replaceContent(target, html);
      target.dataset.loaded = "1";
      return true;
    } catch (error) {
      target.innerHTML =
        '<div class="px-6 py-6 text-sm text-rose-600">详情加载失败，请稍后重试。</div>';
      showToast(error.message || "详情加载失败", "error");
      return false;
    }
  };

  function snapshotImageCategories(rootEl) {
    var snapshot = {};
    var hiddenInputs = rootEl.querySelectorAll("input[type=hidden][data-image-id]");
    hiddenInputs.forEach(function (input) {
      snapshot[input.dataset.imageId] = input.value;
    });
    return snapshot;
  }

  function restoreImageCategories(rootEl, originalImageCats) {
    if (!originalImageCats) return;
    var cards = rootEl.querySelectorAll("[data-image-card]");
    cards.forEach(function (card) {
      var imageId = card.dataset.imageCard;
      if (!imageId || !(imageId in originalImageCats)) return;
      var hidden = card.querySelector("input[type=hidden][data-image-id]");
      if (hidden) hidden.value = originalImageCats[imageId];
      var select = card.querySelector("select[data-subcategory-select]");
      if (!select) return;
      var value = originalImageCats[imageId] || "";
      var parts = value.split("-");
      select.value = parts.length > 1 ? parts[1] : "";
    });
  }

  window.buildConsultationReportDetailState = function (config) {
    return {
      editing: false,
      saving: false,
      originalInterpretation: null,
      originalImageCats: null,
      reportId: config.reportId,
      deleteUrl: config.deleteUrl,
      saveUrl: config.saveUrl,
      recordType: config.recordType,
      subCategory: config.subCategory || "",
      interpretation: config.interpretation || "",
      metricPanelOpenKey: "",
      activeMetricData: null,
      metricCache: {},
      metricLoadingKey: "",
      metricError: "",
      /**
       * 解析指标行的异常等级。
       * @param {Object} row 指标行对象，至少包含 abnormal_flag 字段。
       * @returns {string} 返回 high、low 或 normal，用于统一映射单元格样式。
       */
      getMetricAbnormalLevel: function (row) {
        if (!row || !row.abnormal_flag) {
          return "normal";
        }
        if (row.abnormal_flag === "HIGH") {
          return "high";
        }
        if (row.abnormal_flag === "LOW") {
          return "low";
        }
        return "normal";
      },
      /**
       * 获取当前指标行的异常高亮样式。
       * @param {Object} row 指标行对象，至少包含 abnormal_flag 字段。
       * @returns {string} 返回适用于单元格的 Tailwind 颜色类字符串。
       */
      getMetricHighlightClass: function (row) {
        var abnormalLevel = this.getMetricAbnormalLevel(row);
        if (abnormalLevel === "high") {
          return "bg-rose-100 text-rose-700";
        }
        if (abnormalLevel === "low") {
          return "bg-sky-100 text-sky-700";
        }
        return "text-slate-700";
      },
      /**
       * 获取指标表格单元格的最终样式类。
       * @param {Object} row 指标行对象，至少包含 abnormal_flag 字段。
       * @param {Object} options 单元格控制参数，包含 value 和 allowPlaceholderNeutral。
       * @returns {string} 返回最终绑定到单元格的颜色类；当占位值需要保持中性时返回默认样式。
       */
      getMetricCellClass: function (row, options) {
        var resolvedOptions = options || {};
        var value = resolvedOptions.value;
        var allowPlaceholderNeutral = Boolean(resolvedOptions.allowPlaceholderNeutral);
        if (allowPlaceholderNeutral && value === "-") {
          return "text-slate-600";
        }
        return this.getMetricHighlightClass(row);
      },
      startEdit: function (rootEl) {
        if (this.saving) return;
        this.originalInterpretation = this.interpretation;
        this.originalImageCats = snapshotImageCategories(rootEl);
        this.editing = true;
      },
      cancelEdit: function (rootEl) {
        if (this.saving) return;
        if (this.originalInterpretation !== null) {
          this.interpretation = this.originalInterpretation;
        }
        restoreImageCategories(rootEl, this.originalImageCats);
        this.editing = false;
      },
      saveChanges: async function (rootEl) {
        if (this.saving) return;
        this.saving = true;
        try {
          var updates = [];
          var hiddenInputs = rootEl.querySelectorAll("input[type=hidden][data-image-id]");
          hiddenInputs.forEach(
            function (input) {
              var imageId = input.dataset.imageId;
              var currentValue = input.value;
              if (
                this.originalImageCats &&
                imageId in this.originalImageCats &&
                this.originalImageCats[imageId] === currentValue
              ) {
                return;
              }
              updates.push({ image_id: imageId, category: currentValue });
            }.bind(this)
          );

          var payload = await fetchJson(this.saveUrl, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-CSRFToken": getCookie("csrftoken"),
            },
            body: JSON.stringify({
              image_updates: updates,
              record_type: this.recordType,
              sub_category: this.subCategory,
              interpretation: this.interpretation,
            }),
          });

          var summaryNode = document.getElementById("report-row-summary-" + this.reportId);
          if (summaryNode && payload.summary_html) {
            summaryNode.outerHTML = payload.summary_html;
            summaryNode = document.getElementById("report-row-summary-" + this.reportId);
            processNode(summaryNode);
          }

          var detailBody = document.getElementById("report-detail-body-" + this.reportId);
          if (detailBody && payload.detail_html) {
            replaceContent(detailBody, payload.detail_html);
          }

          showToast(payload.message || "保存成功", payload.type || "success");
        } catch (error) {
          showToast(error.message || "保存失败，请稍后重试", "error");
        } finally {
          this.saving = false;
        }
      },
      confirmDelete: function () {
        window.openConsultationRecordDeleteModal({
          eventId: this.reportId,
          deleteUrl: this.deleteUrl,
        });
      },
      toggleMetricPanel: async function (imageKey, metricsUrl) {
        if (this.metricPanelOpenKey === imageKey) {
          this.metricPanelOpenKey = "";
          this.activeMetricData = null;
          this.metricError = "";
          this.metricLoadingKey = "";
          return;
        }
        this.metricPanelOpenKey = imageKey;
        this.metricError = "";

        if (this.metricCache[imageKey]) {
          this.activeMetricData = this.metricCache[imageKey];
          return;
        }

        this.metricLoadingKey = imageKey;
        this.activeMetricData = null;

        try {
          var response = await fetch(metricsUrl, {
            headers: { "X-Requested-With": "XMLHttpRequest" },
          });
          var payload = await response.json();
          if (!response.ok || payload.status !== "success") {
            throw new Error(payload.message || "指标数据加载失败，请重试");
          }
          this.metricCache[imageKey] = payload;
          if (this.metricPanelOpenKey === imageKey) {
            this.activeMetricData = payload;
          }
        } catch (error) {
          if (this.metricPanelOpenKey === imageKey) {
            this.metricError = "指标数据加载失败，请重试";
          }
        } finally {
          if (this.metricLoadingKey === imageKey) {
            this.metricLoadingKey = "";
          }
        }
      },
    };
  };

  window.saveImageArchiveGroup = async function (rootEl, state, url) {
    if (state.isSaving) return;
    state.isSaving = true;

    try {
      var updates = [];
      var items = rootEl.querySelectorAll(".image-item-data");
      items.forEach(function (item) {
        if (item.dataset.isArchived === "1") return;
        var catSelect = item.querySelector(".cat-select");
        var subInput = item.querySelector(".sub-input");
        var dateInput = item.querySelector(".date-input");
        var catVal = catSelect ? catSelect.value : "";
        var subVal = subInput ? subInput.value : "";
        var dateVal = dateInput ? dateInput.value : "";
        if (!catVal || !dateVal) {
          throw new Error("请完善未归档图片的类目和报告日期");
        }
        var fullCat = catVal;
        if (catVal === "复查") {
          if (!subVal) {
            throw new Error("请为复查类型的图片选择二级分类");
          }
          fullCat = catVal + "-" + subVal;
        }
        updates.push({
          image_id: item.dataset.id,
          category: fullCat,
          report_date: dateVal,
        });
      });

      if (!updates.length) {
        state.isGroupEditing = false;
        showToast("当前无未归档图片可提交", "info");
        return;
      }

      var html = await fetchText(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify({ updates: updates }),
      });
      replaceContent(getReportsContentTarget(), html);
      showToast("归档保存成功", "success");
    } catch (error) {
      showToast(error.message || "保存失败", "error");
    } finally {
      state.isSaving = false;
    }
  };

  window.ignoreArchiveAiWarnings = async function (url) {
    try {
      var html = await fetchText(url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": getCookie("csrftoken"),
        },
        body: JSON.stringify({}),
      });
      replaceContent(getReportsContentTarget(), html);
      showToast("已忽略告警并重新同步", "success");
    } catch (error) {
      showToast(error.message || "处理失败", "error");
    }
  };

  var deleting = false;
  var pendingDeleteUrl = "";
  var pendingDeleteEventId = null;

  function setDeleteModalOpen(open) {
    var modal = document.getElementById("consultation-delete-modal");
    if (!modal) return;
    modal.classList.toggle("hidden", !open);
  }

  function setDeleteModalLoading(isLoading) {
    var confirmBtn = document.getElementById("consultation-delete-confirm-btn");
    var cancelBtn = document.getElementById("consultation-delete-cancel-btn");
    if (!confirmBtn || !cancelBtn) return;
    confirmBtn.disabled = isLoading;
    cancelBtn.disabled = isLoading;
    if (isLoading) {
      confirmBtn.dataset.prevText = confirmBtn.textContent;
      confirmBtn.textContent = "删除中...";
      confirmBtn.classList.add("opacity-60", "cursor-wait");
      cancelBtn.classList.add("opacity-60", "cursor-not-allowed");
    } else {
      confirmBtn.textContent = confirmBtn.dataset.prevText || "确定";
      confirmBtn.classList.remove("opacity-60", "cursor-wait");
      cancelBtn.classList.remove("opacity-60", "cursor-not-allowed");
    }
  }

  function closeConsultationRecordDeleteModal() {
    if (deleting) return;
    pendingDeleteUrl = "";
    pendingDeleteEventId = null;
    setDeleteModalOpen(false);
  }

  window.openConsultationRecordDeleteModal = function (options) {
    var opts = options || {};
    pendingDeleteUrl = opts.deleteUrl || "";
    pendingDeleteEventId = opts.eventId;
    if (!pendingDeleteUrl || !pendingDeleteEventId) {
      showToast("删除参数缺失", "error");
      return;
    }
    setDeleteModalLoading(false);
    setDeleteModalOpen(true);
  };

  async function doDeleteConsultationRecord() {
    if (deleting || !pendingDeleteUrl || !pendingDeleteEventId) return;
    deleting = true;
    setDeleteModalLoading(true);
    try {
      var data = await fetchJson(pendingDeleteUrl, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCookie("csrftoken"),
          "X-Requested-With": "XMLHttpRequest",
        },
      });

      var row = document.getElementById("report-row-" + pendingDeleteEventId);
      if (row) {
        row.style.transition = "all 0.2s";
        row.style.opacity = "0";
        row.style.transform = "scale(0.98)";
        setTimeout(function () {
          row.remove();
          if (!document.querySelector("[data-event-id]")) {
            document.body.dispatchEvent(new CustomEvent("refresh-records-list", { bubbles: true }));
          }
        }, 200);
      }

      showToast(data.message || "删除成功", "success");
      closeConsultationRecordDeleteModal();
    } catch (error) {
      showToast(error.message || "删除失败，请稍后重试", "error");
    } finally {
      deleting = false;
      setDeleteModalLoading(false);
    }
  }

  function isReportsRequest(event) {
    var detail = event.detail || {};
    var elt = detail.elt || event.target;
    return !!(elt && (elt.closest("#consultation-records-root") || elt.closest("#reports-history-content")));
  }

  document.body.addEventListener("htmx:responseError", function (event) {
    if (!isReportsRequest(event)) return;
    showToast("列表刷新失败，请稍后重试", "error");
  });

  document.body.addEventListener("htmx:sendError", function (event) {
    if (!isReportsRequest(event)) return;
    showToast("网络异常，列表刷新失败", "error");
  });

  document.body.addEventListener("htmx:afterSwap", function (event) {
    var target = event.detail && event.detail.target;
    if (target && target.id === "reports-history-content") {
      processNode(target);
    }

    var pendingId = window.__pendingConsultationEventId;
    if (!pendingId) return;
    if (!target || (target.id !== "reports-history-content" && target.id !== "patient-content")) return;

    var row = document.querySelector('[data-event-id="' + pendingId + '"]');
    if (!row) {
      showToast("已新增记录，但当前页未找到（可能受分页/筛选影响）", "error");
      window.__pendingConsultationEventId = null;
      return;
    }

    row.scrollIntoView({ block: "center" });
    row.classList.add("ring-2", "ring-emerald-400");
    setTimeout(function () {
      row.classList.remove("ring-2", "ring-emerald-400");
    }, 1200);
    window.__pendingConsultationEventId = null;
  });

  document.body.addEventListener("click", function (event) {
    var target = event.target;
    if (!target) return;
    if (target.id === "consultation-delete-modal") {
      closeConsultationRecordDeleteModal();
      return;
    }
    if (target.id === "consultation-delete-cancel-btn") {
      closeConsultationRecordDeleteModal();
      return;
    }
    if (target.id === "consultation-delete-confirm-btn") {
      doDeleteConsultationRecord();
    }
  });

  document.body.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeConsultationRecordDeleteModal();
    }
  });
})();
