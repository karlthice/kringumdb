/**
 * item-dialog.js - Item create/edit dialog
 * Port of doInsertUpdateItem from Default.js
 */

function doInsertUpdateItem(inElement, inItem) {
    // Fetch areas for the Tag multi-select
    API.get("areas").then(function (areaData) {
        var aAreas = areaData.Areas;
        var aAreaList = aAreas.map(function (area) { return area.Caption; });

        var dtDate = new Date();
        var sDate = dtDate.getDate() + "." + (dtDate.getMonth() + 1) + "." + dtDate.getFullYear();

        // Parse tag string into array for multi-select matching
        var currentTags = inItem.Tag ? inItem.Tag.split(';') : [];

        QuickDialog(inElement,
            { Caption: "Skrá atriði", minWidth: '800px', tag: 'New', noautoclose: true },
            {
                ID: inItem.ID ? String(inItem.ID) : '',
                Name: inItem.Name || '',
                NameEng: inItem.NameEng || '',
                GPS: inItem.GPS || '',
                Tag: currentTags,
                Story: inItem.Story || '',
                StoryEng: inItem.StoryEng || '',
                Link: inItem.Link || '',
                LinkEng: inItem.LinkEng || '',
                Visibility: inItem.Visibility != null ? String(inItem.Visibility) : '0',
                Ref: inItem.Ref || ('Sótt af Wikipedia ' + sDate)
            },
            [
                { Caption: 'ID', id: 'ID', PropertyType: 'String' },
                { Caption: 'Nafn', id: 'Name', PropertyType: 'String' },
                { Caption: 'GPS', id: 'GPS', PropertyType: 'String' },
                { Caption: 'Tag', id: 'Tag', multiple: true, PropertyType: 'Select', ValueData: aAreaList, TextData: aAreaList },
                { Caption: 'Texti', id: 'Story', PropertyType: 'Text', maxlength: 4000, rows: 9 },
                { Caption: 'Reference', id: 'Ref', PropertyType: 'Text', maxlength: 3000 },
                { Caption: 'Sýnileiki', id: 'Visibility', PropertyType: 'Select', Texts: 'Í aðallista;Einungis í svæði', Values: '0;1' },
                { Caption: 'Link', id: 'Link', PropertyType: 'String', maxlength: 1000 },
                { Caption: '', id: 'b', PropertyType: 'ColumnBreak' },
                { Caption: 'Nafn (Enska)', id: 'NameEng', PropertyType: 'String' },
                { Caption: 'Texti (Enska)', id: 'StoryEng', PropertyType: 'Text', maxlength: 4000, rows: 9 },
                { Caption: 'Link (enska)', id: 'LinkEng', PropertyType: 'String', maxlength: 1000 },
                { Caption: 'Þýða texta', id: 'DoTranslate', PropertyType: 'Button' },
                { Caption: 'Lesa íslensku', id: 'ReadIcelandic', PropertyType: 'Button' },
                { Caption: 'Lesa ensku', id: 'ReadEnglish', PropertyType: 'Button' },
                { Caption: 'Nálægt', id: 'DisplayNear', PropertyType: 'Button' }
            ],
            function (inObject) {
                // Handle Translate button
                if (inObject.DoTranslate) {
                    API.call("translate", { text: inObject.Story }).then(function (data) {
                        if (data.error) {
                            alert(data.error);
                        } else {
                            $("[data-id='StoryEng']").val(data.translatedText);
                        }
                    });
                    API.call("translate", { text: inObject.Name }).then(function (data) {
                        if (data.error) return;
                        $("[data-id='NameEng']").val(data.translatedText);
                    });
                    inObject.DoTranslate = false;
                    return false;
                }

                // Handle DisplayNear button
                if (inObject.DisplayNear) {
                    API.call("nearby", { gps: inObject.GPS }).then(function (data) {
                        QuickDialog(inElement,
                            { Caption: "Nálægir staðir", minWidth: '600px', tag: 'Near' },
                            { TableData: data.Nearby },
                            [
                                { Caption: 'Staðsetningar', id: 'TableData', PropertyType: 'Table' }
                            ],
                            function () { return true; }
                        );
                    });
                    inObject.DisplayNear = false;
                    return false;
                }

                // Handle Read Icelandic button (browser TTS)
                if (inObject.ReadIcelandic) {
                    var text = $("[data-id='Story']").val();
                    speakText(text, 'is-IS');
                    inObject.ReadIcelandic = false;
                    return false;
                }

                // Handle Read English button (browser TTS)
                if (inObject.ReadEnglish) {
                    var text = $("[data-id='StoryEng']").val();
                    speakText(text, 'en-US');
                    inObject.ReadEnglish = false;
                    return false;
                }

                // Save - validate required fields
                if (inObject.Name && inObject.GPS && inObject.Tag && inObject.Story) {
                    API.call("items/save", {
                        id: inObject.ID,
                        name: inObject.Name,
                        name_eng: inObject.NameEng,
                        gps: inObject.GPS,
                        tag: arrayToString(inObject.Tag),
                        fromdate: '',
                        todate: '',
                        story: inObject.Story,
                        story_eng: inObject.StoryEng,
                        ref: inObject.Ref,
                        link: inObject.Link,
                        link_eng: inObject.LinkEng,
                        visibility: inObject.Visibility
                    }).then(function () {
                        CloseQuickDialog("New");
                        Render("");
                    });
                    return false; // keep open until async save completes (dialog closed in .then)
                } else {
                    return "Ekki allt skráð";
                }
            }
        );
    });
}

/**
 * Text-to-speech using browser Web Speech API
 */
function speakText(text, lang) {
    if (!text) return;
    if (!('speechSynthesis' in window)) {
        alert('Talgervi ekki stutt í þessum vafra');
        return;
    }
    window.speechSynthesis.cancel();
    var utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = lang;
    utterance.rate = 1;
    window.speechSynthesis.speak(utterance);
}
