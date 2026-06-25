/**
 * item-dialog.js - Item create/edit dialog
 * Port of doInsertUpdateItem from Default.js
 */

var TAG_LIST = ['Náttúra', 'Saga', 'Menning', 'Fólk', 'Ferð', 'Bók', 'Kringum', 'Gisting'];

function doInsertUpdateItem(inElement, inItem) {
  API.get("areas").then(function (areaData) {
    var aAreas = areaData.Areas || [];
    var areaIds = aAreas.map(function (a) { return String(a.ID); });
    var areaCaptions = aAreas.map(function (a) { return a.Caption; });

    // Parse tag string into array for multi-select matching
    var currentTags = inItem.Tag ? inItem.Tag.split(';') : [];

    QuickDialog(inElement,
        { Caption: "Skrá atriði", minWidth: '800px', tag: 'New', noautoclose: true },
        {
            ID: inItem.ID ? String(inItem.ID) : '',
            Name: inItem.Name || '',
            NameEng: inItem.NameEng || '',
            GPS: inItem.GPS || '',
            Area: (inItem.AreaIds || []).map(String),
            Tag: currentTags,
            Story: inItem.Story || '',
            StoryEng: inItem.StoryEng || '',
            Link: inItem.Link || '',
            LinkEng: inItem.LinkEng || '',
            Visibility: inItem.Visibility != null ? String(inItem.Visibility) : '0',
            Ref: inItem.Ref || 'Stratos ehf'
        },
        [
            { Caption: 'ID', id: 'ID', PropertyType: 'String' },
            { Caption: 'Nafn', id: 'Name', PropertyType: 'String' },
            { Caption: 'GPS', id: 'GPS', PropertyType: 'String' },
            { Caption: 'Svæði', id: 'Area', multiple: true, PropertyType: 'Select', ValueData: areaIds, TextData: areaCaptions },
            { Caption: 'Tag', id: 'Tag', multiple: true, PropertyType: 'Select', ValueData: TAG_LIST, TextData: TAG_LIST },
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
            { Caption: 'Nálægt', id: 'DisplayNear', PropertyType: 'Button' },
            { Caption: 'Eyða', id: 'DoDelete', PropertyType: 'Button', isred: true }
        ],
            function (inObject) {
                // Handle Delete button
                if (inObject.DoDelete) {
                    inObject.DoDelete = false;
                    if (inObject.ID && confirm("Ertu viss um að þú viljir eyða þessu atriði?")) {
                        API.call("items/delete", { id: inObject.ID }).then(function () {
                            CloseQuickDialog("New");
                            Render("");
                        });
                    }
                    return false;
                }

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

                // Normalize GPS: a "lat,lng" coordinate or the NOLOC sentinel
                // (any case) for items with no location. Anything else is invalid.
                var gps = (inObject.GPS || '').trim();
                if (/^noloc$/i.test(gps)) {
                    gps = 'NOLOC';
                } else if (!/^\s*-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?\s*$/.test(gps)) {
                    gps = '';  // invalid -> fails the required-field check below
                }

                // Save - validate required fields
                if (inObject.Name && gps && inObject.Tag && inObject.Story) {
                    API.call("items/save", {
                        id: inObject.ID,
                        name: inObject.Name,
                        name_eng: inObject.NameEng,
                        gps: gps,
                        tag: arrayToString(inObject.Tag),
                        fromdate: '',
                        todate: '',
                        story: inObject.Story,
                        story_eng: inObject.StoryEng,
                        ref: inObject.Ref,
                        link: inObject.Link,
                        link_eng: inObject.LinkEng,
                        visibility: inObject.Visibility,
                        areas: inObject.Area || []
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
