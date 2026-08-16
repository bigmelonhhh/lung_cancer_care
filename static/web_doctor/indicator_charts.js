(function (window) {
  "use strict";

  var charts = window.LCCCharts = window.LCCCharts || {};

  function escapeHtml(value) {
    if (
      window.echarts
      && window.echarts.format
      && typeof window.echarts.format.encodeHTML === "function"
    ) {
      return window.echarts.format.encodeHTML(String(value));
    }

    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function resolveValue(param) {
    var value = param ? param.value : null;
    if (
      (value === null || value === undefined)
      && param
      && param.data
      && typeof param.data === "object"
      && Object.prototype.hasOwnProperty.call(param.data, "value")
    ) {
      value = param.data.value;
    }
    return value;
  }

  charts.formatAxisTooltip = function (params, isMissing) {
    var items = Array.isArray(params) ? params : (params ? [params] : []);
    var rows = [];
    var axisValue;

    items.forEach(function (param) {
      var value = resolveValue(param);
      var missing = value === null || value === undefined;
      if (!missing && typeof isMissing === "function") {
        missing = isMissing(param, value) === true;
      }
      if (missing) return;

      if (axisValue === undefined) {
        axisValue = param.axisValue;
      }
      rows.push(
        (param.marker || "")
        + " "
        + escapeHtml(param.seriesName || "")
        + ": "
        + escapeHtml(value)
      );
    });

    if (!rows.length) return "";
    return [escapeHtml(axisValue === undefined ? "" : axisValue)]
      .concat(rows)
      .join("<br/>");
  };
})(window);
