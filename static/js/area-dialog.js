/**
 * area-dialog.js - Area list and area editor dialogs
 * Port of doAreas and doInsertUpdateArea from Default.js
 */

function doAreas(inElement) {
    API.get("areas").then(function (data) {
        var aAreas = data.Areas;
        var aAreaList = aAreas.map(function (area) {
            return { key: area.Caption, value: String(area.ID) };
        });

        QuickDialog(inElement,
            { Caption: "Svæði", minWidth: '600px', tag: 'Areas' },
            { TableData: aAreaList },
            [
                { Caption: '', id: 'TableData', PropertyType: 'Table', ClickableKeys: true },
                { Caption: 'Nýtt svæði', id: 'ButtonNew', PropertyType: 'Button' }
            ],
            function (inAreaID) {
                if (inAreaID && inAreaID.ButtonNew) {
                    doInsertUpdateArea(inElement, "new");
                    return true;
                } else if (typeof inAreaID === 'string') {
                    // Clicked on an area in the table
                    doInsertUpdateArea(inElement, inAreaID);
                    return false;
                }
                return false;
            }
        );
    });
}

function doInsertUpdateArea(inElement, areaId) {
    API.get("areas/" + areaId).then(function (data) {
        var oArea = data.Area;
        if (!oArea.Media) oArea.Media = "";

        // Fetch items within this area's geographic radius
        var itemsPromise = oArea.ID
            ? API.get("areas/" + oArea.ID + "/items")
            : Promise.resolve({ Items: [] });
        itemsPromise.then(function (itemData) {
            var relatedItems = itemData.Items || [];
            oArea.TableData = relatedItems.map(function (item) {
                return { key: item.Name, value: String(item.ID) };
            });

            QuickDialog(inElement,
                { Caption: "Svæði", minWidth: '1000px', maxHeight: '500px', tag: 'SingleArea' },
                oArea,
                [
                    { Caption: 'Nafn', id: 'Caption', PropertyType: 'String' },
                    { Caption: 'Nafn (enska)', id: 'CaptionEng', PropertyType: 'String' },
                    { Caption: 'Lýsing', id: 'Description', PropertyType: 'Text' },
                    { Caption: 'Lýsing (enska)', id: 'DescriptionEng', PropertyType: 'Text' },
                    { Caption: 'Mynd', id: 'Media', PropertyType: 'String' },
                    { Caption: 'GPS', id: 'GPS', PropertyType: 'String' },
                    { Caption: 'Radíus í metrum', id: 'Radius', PropertyType: 'Number' },
                    { Caption: 'Sýnileiki', id: 'Visibility', PropertyType: 'Select', Texts: 'Ekki í aðallista;Í aðallista', Values: '0;1' },
                    { Caption: '', id: 'b', PropertyType: 'ColumnBreak' },
                    { Caption: 'Tengdir staðir', id: 'TableData', PropertyType: 'Table', ClickableKeys: true }
                ],
                function (result) {
                    // Handle clicking on a related item in the table
                    if (typeof result === 'string' && !result.Caption) {
                        var clickedItem = relatedItems.find(function (item) {
                            return String(item.ID) === result;
                        });
                        if (clickedItem) {
                            doInsertUpdateItem(inElement, clickedItem);
                        }
                        return false;
                    }

                    // Validate
                    if (!result.Caption || !result.CaptionEng || !result.GPS) {
                        return "Þarf að fylla út svæði";
                    }

                    // Save
                    API.call("areas/save", {
                        id: oArea.ID ? String(oArea.ID) : '',
                        caption: result.Caption,
                        caption_eng: result.CaptionEng,
                        gps: result.GPS,
                        radius: result.Radius,
                        description: result.Description,
                        description_eng: result.DescriptionEng,
                        media: result.Media,
                        visibility: result.Visibility
                    }).then(function () {
                        alert("Vistað");
                    });
                    return true;
                }
            );
        });
    });
}
