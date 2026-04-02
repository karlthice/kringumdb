/**
 * app.js - Main application logic
 * Handles list rendering, toolbar events, search
 */

// Convert array to semicolon-separated string (for tag multi-select)
function arrayToString(arr) {
    if (!arr || arr.length === 0) return "";
    return Array.isArray(arr) ? arr.join(";") : arr;
}

function doSearch(filter) {
    Render(filter);
}

function doRefresh(filter) {
    Render(filter);
}

function doExport(language) {
    API.call("export", { language: language || '' }).then(function () {
        alert('Komið!');
    });
}

function Render(filter) {
    var eList = $(".IceList");
    eList.html("Augnablik ...");

    if (!filter) filter = "";

    API.call("items", { filter: filter }).then(function (oData) {
        if (oData.Error) {
            alert(oData.Error);
            return;
        }

        eList.empty();

        if (oData.Items.length > 0) {
            // Translation percentage badge
            var dTotal = oData.TotalTranslate;
            var dDone = oData.TotalDone;
            var dPerc = dTotal > 0 ? (dDone / dTotal * 100) : 0;
            eList.append("<span class='IceBadge'>" + Math.round(dPerc) + "%</span><br><br>");

            for (var i = 0; i < oData.Items.length; i++) {
                var oItem = oData.Items[i];
                var sTranslated = "";
                if (oItem.StoryEng) {
                    sTranslated = "<span class='IceBadge'>Enska</span>";
                }
                var tagDisplay = oItem.Tag ? "<span style='background-color:lightgray;border-radius:4px;padding:2px'>" + escapeHtml(oItem.Tag) + "</span>" : "";
                var eItem = $("<div class='IceItem'>" +
                    "<span style='margin-right:16px'>" + oItem.ID + "</span>" +
                    "<span class='IceItemName'><b>" + escapeHtml(oItem.Name) + "</b></span>&nbsp;" +
                    tagDisplay + sTranslated +
                    "</div>").appendTo(eList);
                eItem.data("object", oItem);
            }
        } else {
            eList.html("Ekkert fannst");
        }
    });
}

// Event delegation for item clicks
$(document).on("click", ".IceItemName", function () {
    var oItem = $(this).parent().data("object");
    doInsertUpdateItem($(this), oItem);
});

// Toolbar events
$(document).on("click", ".IceNew", function () {
    doInsertUpdateItem($(this), {});
});

$(document).on("click", ".IceArea", function () {
    doAreas($(this));
});

$(document).on("click", ".IceExport", function () {
    doExport('');
});

$(document).on("click", ".IceExportEng", function () {
    doExport('ENG');
});

$(document).on("click", ".IceSearch", function () {
    doSearch($(".IceSearchField").val());
});

$(document).on("click", ".IceRefresh", function () {
    doRefresh();
});

$(document).on("click", ".IceSingle", function () {
    doRefresh($(this).attr("data-filter"));
});

// Enter key in search field
$(document).on("keypress", ".IceSearchField", function (e) {
    if (e.which === 13) {
        doSearch($(this).val());
    }
});

// Page load
$(function () {
    Render("");
});
