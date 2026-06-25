/**
 * app.js - Main application logic
 * Handles list rendering, toolbar events, search
 */

// Convert array to semicolon-separated string (for tag multi-select)
function arrayToString(arr) {
    if (!arr || arr.length === 0) return "";
    return Array.isArray(arr) ? arr.join(";") : arr;
}

// True if gps is a usable "lat,lon" coordinate. Empty, the NOLOC sentinel
// (any case), and non-numeric values count as no location, so such items/areas
// are not placed on the map.
function hasLocation(gps) {
    gps = (gps || '').replace(' ', '');
    if (!gps || gps.toUpperCase() === 'NOLOC' || gps.indexOf(',') < 0) return false;
    var parts = gps.split(',');
    return !isNaN(parseFloat(parts[0])) && !isNaN(parseFloat(parts[1]));
}

function doSearch(filter) {
    Render(filter);
}

function doRefresh(filter) {
    Render(filter);
}

function doExport(language) {
    window.location.href = '/api/export?language=' + encodeURIComponent(language || '');
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
                var areaDisplay = oItem.Area ? " <span style='background-color:#5bc0de;color:white;border-radius:4px;padding:2px;font-size:90%'>" + escapeHtml(oItem.Area) + "</span>" : "";
                var eItem = $("<div class='IceItem'>" +
                    "<span style='margin-right:16px'>" + oItem.ID + "</span>" +
                    "<span class='IceItemName'><b>" + escapeHtml(oItem.Name) + "</b></span>&nbsp;" +
                    tagDisplay + areaDisplay + sTranslated +
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

// --- Map ---

var mapInstance = null;
var mapMarkers = null;
var mapAreas = null;
var userLocationMarker = null;

function updateMapCounter() {
    var count = 0;
    if (mapMarkers) {
        mapMarkers.eachLayer(function (layer) {
            if (layer._itemData && !layer._filteredOut) count++;
        });
    }
    $("#map-counter").text(count + " atriði");
}

var TAG_COLORS = {
    'Náttúra': '#228B22',
    'Saga': '#8B4513',
    'Menning': '#6A0DAD',
    'Fólk': '#FF8C00',
    'Bók': '#4169E1',
    'Ferð': '#DC143C',
    'Kringum': '#20B2AA',
    'Gisting': '#808080',
    'Hlíðar': '#2E8B57',
};

function getTagColor(tag) {
    if (!tag) return '#3388ff';
    for (var key in TAG_COLORS) {
        if (tag.indexOf(key) >= 0) return TAG_COLORS[key];
    }
    return '#3388ff';
}

function buildItemPopup(item) {
    var html = "<div style='max-width:350px;max-height:300px;overflow-y:auto'>" +
        "<b style='cursor:pointer' class='map-item-link' data-id='" + item.ID + "'>" +
        escapeHtml(item.Name) + "</b><br>" +
        "<span style='color:gray;font-size:11px'>" + escapeHtml(item.Tag || '') + "</span>" +
        (item.Area ? " <span style='background:#5bc0de;color:white;padding:1px 5px;border-radius:4px;font-size:11px;font-weight:bold'>" + escapeHtml(item.Area) + "</span>" : "") +
        (item.StoryEng ? " <span style='background:darkorange;color:white;padding:1px 5px;border-radius:4px;font-size:11px;font-weight:bold'>English</span>" : "");
    if (item.Story) {
        html += "<hr style='margin:4px 0'><div style='font-size:13px;white-space:pre-wrap'>" +
            escapeHtml(item.Story) + "</div>";
    }
    html += "<hr style='margin:4px 0'><div class='map-edit-link' data-id='" + item.ID + "' " +
        "style='cursor:pointer;display:inline-block;padding:3px 10px;background:#17a2b8;color:white;border-radius:4px;font-size:12px;font-weight:bold'>Breyta</div> " +
        "<div class='map-move-link' data-id='" + item.ID + "' " +
        "style='cursor:pointer;display:inline-block;padding:3px 10px;background:#e67e22;color:white;border-radius:4px;font-size:12px;font-weight:bold;margin-left:4px'>Breyta hnitum</div>";
    html += "</div>";
    return html;
}

function doShowMap() {
    $("#map-overlay").show();

    if (!mapInstance) {
        mapInstance = L.map('map').setView([64.9, -18.5], 6);
        L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
            maxZoom: 17,
            attribution: 'Map data: &copy; <a href="https://openstreetmap.org">OpenStreetMap</a> contributors, ' +
                '<a href="http://viewfinderpanoramas.org">SRTM</a> | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a>'
        }).addTo(mapInstance);

        // Load all items as markers
        mapMarkers = L.layerGroup().addTo(mapInstance);
        API.call("items", { filter: "" }).then(function (oData) {
            for (var i = 0; i < oData.Items.length; i++) {
                var item = oData.Items[i];
                var gps = (item.GPS || '').replace(' ', '');
                if (!hasLocation(gps)) continue;
                var parts = gps.split(',');
                var lat = parseFloat(parts[0]);
                var lon = parseFloat(parts[1]);

                var marker = L.circleMarker([lat, lon], {
                    radius: 5,
                    fillColor: getTagColor(item.Tag),
                    color: '#333',
                    weight: 1,
                    fillOpacity: 0.8
                });
                marker._itemData = item;
                marker.bindPopup(buildItemPopup(item), { minWidth: 300, maxWidth: 400 });
                marker.addTo(mapMarkers);
            }
            updateMapCounter();
        });

        // Load areas as circles
        mapAreas = L.layerGroup();
        API.get("areas").then(function (areaData) {
            var AREA_COLORS = [
                '#228B22', '#8B4513', '#6A0DAD', '#FF8C00', '#4169E1',
                '#DC143C', '#20B2AA', '#2E8B57', '#C71585', '#4682B4', '#DAA520'
            ];
            for (var i = 0; i < areaData.Areas.length; i++) {
                var area = areaData.Areas[i];
                var gps = (area.GPS || '').replace(' ', '');
                if (!hasLocation(gps)) continue;
                var parts = gps.split(',');
                var lat = parseFloat(parts[0]);
                var lon = parseFloat(parts[1]);
                var radius = parseInt(area.Radius) || 1000;

                var color = AREA_COLORS[i % AREA_COLORS.length];
                var circle = L.circle([lat, lon], {
                    radius: radius,
                    color: color,
                    fillColor: color,
                    fillOpacity: 0.12,
                    weight: 2
                });
                var desc = area.Description ? "<hr style='margin:4px 0'><div style='font-size:13px'>" + escapeHtml(area.Description) + "</div>" : "";
                circle.bindPopup(
                    "<div style='max-width:300px'><b>" + escapeHtml(area.Caption) + "</b>" +
                    " <span style='color:gray;font-size:11px'>(" + escapeHtml(area.CaptionEng || '') + ")</span>" +
                    "<br><span style='font-size:11px'>Radíus: " + (radius >= 1000 ? Math.round(radius / 1000) + " km" : radius + " m") + "</span>" +
                    desc + "</div>"
                );
                circle.addTo(mapAreas);
                // Large text label at center
                var label = L.marker([lat, lon], {
                    icon: L.divIcon({
                        className: 'area-label',
                        html: "<div style='font-size:16px;font-weight:bold;color:" + color + ";text-shadow:1px 1px 2px white,-1px -1px 2px white,1px -1px 2px white,-1px 1px 2px white;white-space:nowrap'>" + escapeHtml(area.Caption) + "</div>",
                        iconSize: null,
                        iconAnchor: [0, 0]
                    }),
                    interactive: false
                });
                label.addTo(mapAreas);
            }
        });

        // Item counter below the Leaflet zoom controls (top-left)
        var counterDiv = document.createElement('div');
        counterDiv.id = 'map-counter';
        counterDiv.style.cssText = 'position:absolute;top:100px;left:10px;z-index:5100;background:white;padding:4px 10px;border:2px solid #666;border-radius:4px;box-shadow:0 2px 6px rgba(0,0,0,0.3);font-size:13px;font-weight:bold';
        document.getElementById('map-overlay').appendChild(counterDiv);

        // Toggle control for areas - positioned below the close button
        var toggleDiv = document.createElement('div');
        toggleDiv.id = 'area-toggle';
        toggleDiv.innerHTML = "<label style='display:block;padding:6px 10px;background:white;cursor:pointer;font-size:13px;font-weight:bold;white-space:nowrap;border:2px solid #666;border-radius:4px;box-shadow:0 2px 6px rgba(0,0,0,0.3)'>" +
            "<input type='checkbox' id='area-toggle-cb' style='margin-right:5px'>Svæði</label>";
        document.getElementById('map-overlay').appendChild(toggleDiv);

        // Quick search field below area toggle
        var searchDiv = document.createElement('div');
        searchDiv.id = 'map-search';
        searchDiv.innerHTML = "<input type='text' id='map-search-input' placeholder='Sía á korti...' " +
            "style='width:160px;padding:5px 8px;font-size:13px;border:2px solid #666;border-radius:4px;box-shadow:0 2px 6px rgba(0,0,0,0.3);outline:none'>" +
            "<div id='map-search-clear' style='display:none;cursor:pointer;padding:4px 8px;background:white;border:2px solid #666;border-radius:4px;box-shadow:0 2px 6px rgba(0,0,0,0.3);font-size:11px;font-weight:bold;margin-top:4px;text-align:center'>Hreinsa</div>";
        document.getElementById('map-overlay').appendChild(searchDiv);

        // Locate-me button below the search field
        var locateDiv = document.createElement('div');
        locateDiv.id = 'map-locate';
        locateDiv.innerHTML = "<button type='button' title='Mín staðsetning' " +
            "style='padding:6px 10px;background:white;cursor:pointer;font-size:13px;font-weight:bold;white-space:nowrap;border:2px solid #666;border-radius:4px;box-shadow:0 2px 6px rgba(0,0,0,0.3)'>" +
            "&#x1F4CD; Mín staðsetning</button>";
        document.getElementById('map-overlay').appendChild(locateDiv);

        $(document).on("change", "#area-toggle-cb", function () {
            if (this.checked) {
                mapAreas.addTo(mapInstance);
            } else {
                mapInstance.removeLayer(mapAreas);
            }
        });

        // Filter map markers by caption
        $(document).on("input", "#map-search-input", function () {
            var query = $(this).val().toLowerCase();
            $("#map-search-clear").toggle(query.length > 0);
            mapMarkers.eachLayer(function (layer) {
                if (!layer._itemData) return;
                var name = (layer._itemData.Name || '').toLowerCase();
                var match = !query || name.indexOf(query) >= 0;
                if (match && query) {
                    // Active filter: matched items are bright red and interactive
                    layer.setStyle({ fillColor: '#ff0000', fillOpacity: 1, radius: 7 });
                    layer.setRadius(7);
                    if (layer._path) layer._path.style.pointerEvents = '';
                    layer._filteredOut = false;
                } else if (match) {
                    // No filter: restore normal tag color and interactivity
                    layer.setStyle({ fillColor: getTagColor(layer._itemData.Tag), fillOpacity: 0.8, radius: 5 });
                    layer.setRadius(5);
                    if (layer._path) layer._path.style.pointerEvents = '';
                    layer._filteredOut = false;
                } else {
                    // Filtered out: dim and non-interactive
                    layer.setStyle({ fillOpacity: 0.15, radius: 3, fillColor: '#999' });
                    layer.setRadius(3);
                    if (layer._path) layer._path.style.pointerEvents = 'none';
                    layer._filteredOut = true;
                }
            });
            updateMapCounter();
        });

        $(document).on("click", "#map-search-clear", function () {
            $("#map-search-input").val("").trigger("input");
        });

        $(document).on("click", "#map-locate button", function () {
            if (!navigator.geolocation) {
                alert("Vafrinn styður ekki staðsetningu.");
                return;
            }
            var $btn = $(this).prop("disabled", true);
            navigator.geolocation.getCurrentPosition(
                function (pos) {
                    var lat = pos.coords.latitude;
                    var lng = pos.coords.longitude;
                    mapInstance.flyTo([lat, lng], 14);
                    if (userLocationMarker) {
                        mapInstance.removeLayer(userLocationMarker);
                    }
                    userLocationMarker = L.circleMarker([lat, lng], {
                        radius: 7,
                        color: '#fff',
                        weight: 2,
                        fillColor: '#1976d2',
                        fillOpacity: 1
                    }).addTo(mapInstance);
                    $btn.prop("disabled", false);
                },
                function (err) {
                    alert("Gat ekki sótt staðsetningu: " + err.message);
                    $btn.prop("disabled", false);
                },
                { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 }
            );
        });

        // Relocate banner
        var bannerDiv = document.createElement('div');
        bannerDiv.id = 'map-relocate-banner';
        bannerDiv.style.cssText = 'display:none;position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:5100;background:rgba(230,126,34,0.95);color:white;padding:8px 16px;border-radius:6px;font-size:14px;font-weight:bold;box-shadow:0 2px 8px rgba(0,0,0,0.3)';
        bannerDiv.innerHTML = 'Smelltu á kortið til að velja nýja staðsetningu &nbsp; <span id="map-relocate-cancel" style="cursor:pointer;text-decoration:underline;margin-left:8px">Hætta við</span>';
        document.getElementById('map-overlay').appendChild(bannerDiv);

        // Handle map click for relocation or Ctrl+click to create new item
        mapInstance.on('click', function (e) {
            if (!relocatingItem) {
                if (e.originalEvent.shiftKey) {
                    var lat = e.latlng.lat.toFixed(6);
                    var lng = e.latlng.lng.toFixed(6);
                    doCloseMap();
                    doInsertUpdateItem($(".IceNew"), { GPS: lat + ", " + lng });
                }
                return;
            }

            var newLat = e.latlng.lat.toFixed(6);
            var newLng = e.latlng.lng.toFixed(6);
            var newGps = newLat + ", " + newLng;
            var item = relocatingItem.itemData;
            var marker = relocatingItem.marker;

            // Move the marker
            marker.setLatLng(e.latlng);
            item.GPS = newGps;

            // Clean up legacy ",-" formatting in the caption when relocating
            var cleanedName = (item.Name || '').replace(/,-/g, ', ');
            if (cleanedName !== item.Name) {
                item.Name = cleanedName;
                marker.setPopupContent(buildItemPopup(item));
            }

            // Save to DB
            API.call("items/save", {
                id: String(item.ID),
                name: item.Name,
                name_eng: item.NameEng || '',
                gps: newGps,
                tag: item.Tag,
                story: item.Story,
                story_eng: item.StoryEng || '',
                ref: item.Ref || '',
                link: item.Link || '',
                link_eng: item.LinkEng || '',
                visibility: item.Visibility
            });

            cancelRelocate();
        });
    }

    // Fix Leaflet rendering after overlay becomes visible
    setTimeout(function () { mapInstance.invalidateSize(); }, 100);
}

function doCloseMap() {
    $("#map-overlay").hide();
}

$(document).on("click", ".IceWorld", function () {
    doShowMap();
});

$(document).on("click", "#map-close", function () {
    doCloseMap();
});

$(document).on("keydown", function (e) {
    if (e.key === "Escape") {
        if (relocatingItem) {
            cancelRelocate();
        } else if ($("#map-overlay").is(":visible")) {
            doCloseMap();
        }
    }
});

// --- Relocate item on map ---
var relocatingItem = null; // { id, marker, itemData }

function startRelocate(id) {
    var marker = null;
    var itemData = null;
    mapMarkers.eachLayer(function (layer) {
        if (layer._itemData && String(layer._itemData.ID) === id) {
            marker = layer;
            itemData = layer._itemData;
        }
    });
    if (!marker) return;

    mapInstance.closePopup();
    relocatingItem = { id: id, marker: marker, itemData: itemData };
    $("#map").css("cursor", "crosshair");
    $("#map-relocate-banner").show();
}

function cancelRelocate() {
    relocatingItem = null;
    $("#map").css("cursor", "");
    $("#map-relocate-banner").hide();
}

$(document).on("click", ".map-move-link", function () {
    startRelocate($(this).attr("data-id"));
});

$(document).on("click", "#map-relocate-cancel", function () {
    cancelRelocate();
});

// Clicking item name or edit button in map popup opens the item editor
$(document).on("click", ".map-edit-link, .map-item-link", function () {
    var id = $(this).attr("data-id");
    // Find the item data from the marker
    var itemData = null;
    mapMarkers.eachLayer(function (layer) {
        if (layer._itemData && String(layer._itemData.ID) === id) {
            itemData = layer._itemData;
        }
    });
    if (itemData) {
        doCloseMap();
        doInsertUpdateItem($(this), itemData);
    }
});

// Page load
$(function () {
    Render("");
});
