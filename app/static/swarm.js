/* «Рой агентов»: a slider beside each number field (how many cells, how many at once) and the comb redrawn as they
   move — green work at once, lighter wait their turn, dim are spare. The number fields are what the form sends, so
   without JavaScript the page works as before. Used on /agents/swarm and in the profile's «Соты» on /agents/access. */
(function () {
  "use strict";
  document.querySelectorAll("[data-comb]").forEach(function (box) {
    var cells = box.querySelector('input[type=number][name$="cells"]');
    var at = box.querySelector('input[type=number][name$="at"]');
    var on = box.querySelector('input[type=checkbox][name$="on"]');
    var comb = Array.prototype.slice.call(box.querySelectorAll(".comb .cell"));
    if (!cells) return;
    var pairs = {cells: cells, at: at};

    function draw() {
      var c = Math.max(+cells.min || 1, Math.min(+cells.max || 40, +cells.value || 0));
      var a = at ? Math.max(1, Math.min(c, +at.value || 1)) : 0;
      var live = !on || on.checked;
      comb.forEach(function (cell, i) {
        cell.classList.toggle("run", live && i < a);
        cell.classList.toggle("on", live && i >= a && i < c);
      });
      box.querySelectorAll("input[type=range][data-pair]").forEach(function (range) {
        var field = pairs[range.dataset.pair];
        if (range.dataset.pair === "at") range.max = String(c);  // at once — never more than there are cells
        if (field && document.activeElement !== range) range.value = field.value;
      });
    }

    box.querySelectorAll("input[type=range][data-pair]").forEach(function (range) {
      var field = pairs[range.dataset.pair];
      if (!field) return;
      range.addEventListener("input", function () {
        field.value = range.value;
        if (range.dataset.pair === "cells" && at && +at.value > +range.value) at.value = range.value;
        draw();
      });
    });
    [cells, at, on].forEach(function (el) { if (el) el.addEventListener("input", draw); });
    draw();
  });
})();
