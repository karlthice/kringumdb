/**
 * dialog.js - QuickDialog replacement
 * Supports: String, Text, Number, Select (with multiple), Button, Table, ColumnBreak, Hidden
 */

// Close a QuickDialog by tag, or all if no tag
function CloseQuickDialog(tag) {
    if (tag) {
        $(".kd-dialog[data-tag='" + tag + "']").remove();
    } else {
        $(".kd-dialog").remove();
    }
}

// Close all QuickSelect popups
function CloseQuickSelect() {
    $(".kd-select").remove();
}

/**
 * QuickDialog - modal form generator
 * @param {jQuery} inElement - anchor element for positioning
 * @param {Object} inOptions - { Caption, minWidth, maxHeight, tag, noautoclose, SaveCaption, CancelCaption }
 * @param {Object} inObject - data object with field values
 * @param {Array} inLabels - field definitions [{Caption, id, PropertyType, ...}]
 * @param {Function} inCallback - callback(dataObject) -> true=close, false=keep, string=error+keep
 */
function QuickDialog(inElement, inOptions, inObject, inLabels, inCallback) {
    // Close other dialogs unless noautoclose
    $(".kd-dialog").not("[data-noautoclose='1']").remove();

    if (inOptions.tag) {
        CloseQuickDialog(inOptions.tag);
    }

    // Build dialog shell
    var html = "<div class='kd-dialog'";
    if (inOptions.noautoclose) html += " data-noautoclose='1'";
    if (inOptions.tag) html += " data-tag='" + inOptions.tag + "'";
    html += ">";
    html += "<div class='kd-dialog-close' title='Loka'>&times;</div>";
    if (inOptions.Caption) {
        html += "<div class='kd-dialog-header'>" + inOptions.Caption + "</div>";
    }
    html += "</div>";

    var eDlg = $(html).appendTo("body");

    // Count columns
    var totalColumns = 1;
    for (var i = 0; i < inLabels.length; i++) {
        if (inLabels[i].PropertyType === 'ColumnBreak') totalColumns++;
    }

    // Create column containers
    var colWidth = Math.floor(99 / totalColumns);
    var columns = [];
    for (var c = 0; c < totalColumns; c++) {
        columns.push($("<div class='kd-dialog-column' style='width:" + colWidth + "%;'>").appendTo(eDlg));
    }

    // Render fields
    var currentCol = 0;
    var firstEditId = "";

    for (var i = 0; i < inLabels.length; i++) {
        var l = inLabels[i];
        var v = inObject[l.id];

        if (l.PropertyType === 'ColumnBreak') {
            currentCol++;
            continue;
        }

        var fieldHtml = "<div>";

        // Caption
        if (l.Caption && l.PropertyType !== 'Button' && l.PropertyType !== 'Hidden') {
            fieldHtml += "<div class='kd-dialog-caption'>" + l.Caption + "</div>";
        }

        if (l.PropertyType === 'String') {
            if (!firstEditId && !l.ReadOnly) firstEditId = l.id;
            var maxlen = l.maxlength || 120;
            var readonlyAttr = l.ReadOnly ? " readonly style='width:90%;font-size:14px;padding:4px;border:1px solid #ccc;border-radius:3px;background:#e9ecef;color:#555'" : "";
            fieldHtml += "<input type='text' data-type='String' data-id='" + l.id + "' maxlength='" + maxlen + "' value='" + escapeAttr(v) + "'" + readonlyAttr + "/>";
        }
        else if (l.PropertyType === 'Text') {
            if (!firstEditId) firstEditId = l.id;
            var rows = l.rows || 4;
            var maxlen = l.maxlength || 255;
            fieldHtml += "<textarea data-type='Text' data-id='" + l.id + "' rows='" + rows + "' maxlength='" + maxlen + "'>" + escapeHtml(v || '') + "</textarea>";
        }
        else if (l.PropertyType === 'Number') {
            if (!firstEditId) firstEditId = l.id;
            fieldHtml += "<input type='number' data-type='Number' data-id='" + l.id + "' value='" + escapeAttr(v) + "'/>";
        }
        else if (l.PropertyType === 'Hidden') {
            fieldHtml += "<input type='hidden' data-type='Hidden' data-id='" + l.id + "' value='" + escapeAttr(v) + "'/>";
        }
        else if (l.PropertyType === 'Boolean') {
            fieldHtml += "<input type='checkbox' data-type='Boolean' data-id='" + l.id + "' " + (v ? "checked" : "") + "/>";
        }
        else if (l.PropertyType === 'Select') {
            if (!firstEditId) firstEditId = l.id;
            var texts, values;
            if (l.ValueData) {
                texts = l.TextData;
                values = l.ValueData;
            } else {
                texts = (l.Texts || '').split(';');
                values = (l.Values || '').split(';');
            }
            var multiple = l.multiple ? " multiple" : "";
            fieldHtml += "<select data-type='Select' data-id='" + l.id + "'" + multiple + ">";
            for (var j = 0; j < texts.length; j++) {
                var selected = "";
                if (l.multiple) {
                    if (v && ((Array.isArray(v) && v.indexOf(values[j]) > -1) ||
                              (typeof v === 'string' && v.split(';').indexOf(values[j]) > -1))) {
                        selected = " selected";
                    }
                } else {
                    if (values[j] == v) selected = " selected";
                }
                fieldHtml += "<option value='" + escapeAttr(values[j]) + "'" + selected + ">" + escapeHtml(texts[j]) + "</option>";
            }
            fieldHtml += "</select>";
        }
        else if (l.PropertyType === 'Button') {
            var btnClass = l.isred ? 'kd-btn-danger' : 'kd-btn-action';
            fieldHtml += "<div class='kd-btn " + btnClass + " kd-dialog-button' data-type='Button' data-id='" + l.id + "' data-wasclicked='0'>" + l.Caption + "</div>";
        }
        else if (l.PropertyType === 'Table') {
            fieldHtml += "<div data-type='Table' data-id='" + l.id + "' style='max-height:300px;overflow-y:auto'><table><tbody>";
            if (v && Array.isArray(v)) {
                for (var j = 0; j < v.length; j++) {
                    if (!v[j]) continue;
                    if (l.ClickableKeys) {
                        fieldHtml += "<tr><td class='kd-clickable-key' data-value='" + escapeAttr(v[j].value) + "'>" + escapeHtml(v[j].key) + "</td></tr>";
                    } else {
                        fieldHtml += "<tr><td>" + escapeHtml(v[j].key) + "</td><td>" + escapeHtml(String(v[j].value)) + "</td></tr>";
                    }
                }
            }
            fieldHtml += "</tbody></table></div>";
        }

        fieldHtml += "</div>";
        $(fieldHtml).appendTo(columns[currentCol]);
    }

    // Footer
    var footer = "<div class='kd-dialog-footer'>";
    footer += "<div class='kd-btn kd-btn-cancel kd-dialog-cancel-btn'>" + (inOptions.CancelCaption || "Loka") + "</div>";
    footer += "<div class='kd-btn kd-btn-primary kd-dialog-ok-btn'>" + (inOptions.SaveCaption || "Vista") + "</div>";
    footer += "<div style='clear:both'></div></div>";
    $(footer).appendTo(eDlg);

    // Sizing
    if (inOptions.minWidth) eDlg.css("min-width", inOptions.minWidth);
    if (inOptions.maxHeight) {
        eDlg.css("max-height", inOptions.maxHeight);
        eDlg.css("overflow", "auto");
    }

    // Positioning - near anchor element or centered
    var offset = inElement ? $(inElement).offset() : null;
    if (offset) {
        var x = offset.left;
        var y = offset.top - eDlg.outerHeight();
        if (y < $(window).scrollTop()) y = $(window).scrollTop();
        if (y + eDlg.outerHeight() > $(window).scrollTop() + $(window).height()) {
            y = $(window).scrollTop();
        }
        if (y < 0) y = 0;
        if (x + eDlg.outerWidth() > $(document).width()) {
            x = Math.max(0, $(document).width() - eDlg.outerWidth());
        }
        eDlg.css({ left: x + 'px', top: y + 'px' });
    } else {
        eDlg.css({ left: '50px', top: '50px' });
    }

    // Focus first field
    if (firstEditId) {
        eDlg.find("[data-id='" + firstEditId + "']").focus();
    }

    // --- Event handlers ---

    // Button click -> set flag, trigger OK
    eDlg.find(".kd-dialog-button").off("click").on("click", function () {
        $(this).attr("data-wasclicked", "1");
        eDlg.find(".kd-dialog-ok-btn").trigger("click");
        $(this).attr("data-wasclicked", "0");
    });

    // ClickableKey handler
    eDlg.find(".kd-clickable-key").off("click").on("click", function () {
        var value = $(this).attr("data-value");
        eDlg.hide();
        var result = inCallback(value);
        if (result === false) {
            eDlg.show();
        } else if (result && result !== true) {
            eDlg.show();
            alert(result);
        }
    });

    // OK handler
    eDlg.find(".kd-dialog-ok-btn").off("click").on("click", function () {
        // Gather values
        eDlg.find("[data-id]").each(function () {
            var id = $(this).attr("data-id");
            var type = $(this).attr("data-type");

            if (type === 'Boolean') {
                inObject[id] = $(this).is(":checked");
            } else if (type === 'Button') {
                inObject[id] = $(this).attr("data-wasclicked") === "1";
            } else if (type === 'Table') {
                // don't overwrite table data
            } else if (type === 'Select') {
                inObject[id] = $(this).val();
            } else {
                inObject[id] = $(this).val();
            }
        });

        eDlg.hide();
        var result = inCallback(inObject);

        // Reset button flags
        eDlg.find("[data-type='Button']").each(function () {
            var id = $(this).attr("data-id");
            inObject[id] = false;
        });

        if (result !== true && result !== undefined) {
            eDlg.show();
            if (result !== false) {
                alert(result);
            }
        }
    });

    // Cancel/Close
    eDlg.find(".kd-dialog-cancel-btn, .kd-dialog-close").off("click").on("click", function () {
        eDlg.remove();
    });

    // Select2 for selects with many options
    eDlg.find("select").each(function () {
        if ($(this).find("option").length > 50) {
            $(this).select2({ width: "90%", theme: "classic" });
        }
    });

    eDlg.show();
    return eDlg;
}

/**
 * QuickSelect - selection popup
 */
function QuickSelect(inElement, caption, items, callback) {
    CloseQuickSelect();

    var html = "<div class='kd-select'>";
    html += "<div class='kd-select-header'>" + (typeof caption === 'string' ? caption : caption.Caption || '') + "</div>";
    html += "<div class='kd-dialog-close' title='Loka' style='position:absolute;right:8px;top:8px'>&times;</div>";

    for (var i = 0; i < items.length; i++) {
        html += "<div class='kd-select-item' data-value='" + escapeAttr(items[i].Value) + "'>" + escapeHtml(items[i].Caption) + "</div>";
    }
    html += "</div>";

    var eDlg = $(html).appendTo("body");
    eDlg.css({ left: '100px', top: '100px', 'z-index': 3600 });

    eDlg.find(".kd-select-item").on("click", function () {
        var val = $(this).attr("data-value");
        eDlg.remove();
        callback(val);
    });

    eDlg.find(".kd-dialog-close").on("click", function () {
        eDlg.remove();
    });
}

// Utility: escape HTML entities
function escapeHtml(str) {
    if (str == null) return '';
    return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// Utility: escape attribute value
function escapeAttr(str) {
    if (str == null) return '';
    return String(str).replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
