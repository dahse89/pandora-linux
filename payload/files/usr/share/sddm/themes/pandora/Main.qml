import QtQuick
import QtQuick.Controls.Basic

Rectangle {
    id: root
    width: 1280
    height: 800
    color: theme.base

    readonly property QtObject colors: theme
    property bool pending: false
    property string message: ""
    property bool failed: false

    LayoutMirroring.enabled: Qt.locale().textDirection === Qt.RightToLeft
    LayoutMirroring.childrenInherit: true

    QtObject {
        id: theme
        readonly property color base: "#081629"
        readonly property color panel: "#0b192b"
        readonly property color field: "#172c45"
        readonly property color outline: "#38516f"
        readonly property color foreground: "#f0f5fc"
        readonly property color secondary: "#b1c2d9"
        readonly property color accent: "#9bc5ff"
        readonly property color error: "#ffb4ab"
    }

    function submit() {
        if (pending)
            return;
        if (!username.text.trim()) {
            message = qsTr("Bitte einen Benutzernamen eingeben.");
            failed = true;
            username.forceActiveFocus();
        } else if (!password.text.length) {
            message = qsTr("Bitte das Passwort eingeben.");
            failed = true;
            password.forceActiveFocus();
        } else if (session.currentIndex < 0) {
            message = qsTr("Keine Sitzung verfügbar.");
            failed = true;
        } else {
            message = "";
            failed = false;
            pending = true;
            sddm.login(username.text.trim(), password.text, session.currentIndex);
        }
    }

    function reveal(control) {
        const top = control.mapToItem(viewport.contentItem, 0, 0).y;
        if (top < viewport.contentY)
            viewport.contentY = Math.max(0, top - 8);
        else if (top + control.height > viewport.contentY + viewport.height)
            viewport.contentY = Math.min(viewport.contentHeight - viewport.height,
                                         top + control.height + 8 - viewport.height);
    }

    function clearMessage() {
        message = "";
        failed = false;
    }

    function focusInput() {
        if (username.text.length)
            password.forceActiveFocus();
        else
            username.forceActiveFocus();
    }

    Connections {
        target: sddm
        function onLoginFailed() {
            root.pending = false;
            password.clear();
            showPassword.checked = false;
            root.failed = true;
            root.message = qsTr("Anmeldung fehlgeschlagen. Benutzernamen und Passwort prüfen.");
            root.focusInput();
        }
        function onLoginSucceeded() {
            password.clear();
            showPassword.checked = false;
            root.failed = false;
            root.message = qsTr("Sitzung wird gestartet …");
        }
        function onInformationMessage(message) {
            root.message = message;
        }
    }

    Image {
        anchors.fill: parent
        source: config.background
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
    }
    Rectangle {
        anchors.fill: parent
        color: "#55081629"
    }

    Column {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.margins: 40
        spacing: 4
        visible: root.width >= 1280 && root.height >= 760
        property date now: new Date()
        Timer {
            interval: 1000
            running: parent.visible
            repeat: true
            onTriggered: parent.now = new Date()
        }
        Text {
            text: Qt.formatTime(parent.now, "HH:mm")
            color: theme.foreground
            font.family: "Noto Sans"
            font.pixelSize: 42
            font.weight: Font.Light
        }
        Text {
            text: Qt.formatDate(parent.now, "dddd, d. MMMM yyyy")
            color: theme.secondary
            font.family: "Noto Sans"
            font.pixelSize: 14
        }
    }

    Flickable {
        id: viewport
        objectName: "viewport"
        anchors.fill: parent
        anchors.margins: 20
        contentWidth: width
        contentHeight: Math.max(height, panel.height)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        ScrollBar.vertical: ScrollBar {}

        Rectangle {
            id: panel
            width: Math.min(520, viewport.width)
            height: form.height + 56
            x: (viewport.width - width) / 2
            y: Math.max(0, (viewport.height - height) / 2)
            radius: 16
            color: theme.panel
            border.color: theme.outline

            Column {
                id: form
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.top: parent.top
                anchors.topMargin: 28
                width: Math.min(364, parent.width - 56)
                spacing: 16

                Column {
                    width: parent.width
                    spacing: 4
                    Text {
                        width: parent.width
                        text: "Pandora Linux"
                        color: theme.foreground
                        font.family: "Noto Sans"
                        font.pixelSize: 28
                        font.weight: Font.DemiBold
                        horizontalAlignment: Text.AlignHCenter
                    }
                    Text {
                        width: parent.width
                        text: qsTr("Willkommen zurück")
                        color: theme.secondary
                        font.family: "Noto Sans"
                        font.pixelSize: 14
                        horizontalAlignment: Text.AlignHCenter
                    }
                }

                Column {
                    width: parent.width
                    spacing: 6
                    Text {
                        text: qsTr("Benutzername")
                        color: theme.secondary
                        font.family: "Noto Sans"
                        font.pixelSize: 13
                    }
                    PandoraField {
                        id: username
                        objectName: "username"
                        theme: root.colors
                        onActiveFocusChanged: if (activeFocus) root.reveal(this)
                        width: parent.width
                        text: userModel.lastUser
                        enabled: !root.pending
                        Accessible.name: qsTr("Benutzername")
                        inputMethodHints: Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                        onAccepted: root.submit()
                        onTextEdited: root.clearMessage()
                        KeyNavigation.tab: password
                        KeyNavigation.backtab: shutdown
                    }
                }

                Column {
                    width: parent.width
                    spacing: 6
                    Text {
                        text: qsTr("Passwort")
                        color: theme.secondary
                        font.family: "Noto Sans"
                        font.pixelSize: 13
                    }
                    Row {
                        width: parent.width
                        spacing: 8
                        PandoraField {
                            id: password
                            objectName: "password"
                            theme: root.colors
                            onActiveFocusChanged: if (activeFocus) root.reveal(this)
                            width: parent.width - showPassword.width - parent.spacing
                            enabled: !root.pending
                            Accessible.name: qsTr("Passwort")
                            echoMode: showPassword.checked ? TextInput.Normal : TextInput.Password
                            inputMethodHints: Qt.ImhSensitiveData | Qt.ImhNoPredictiveText | Qt.ImhNoAutoUppercase
                            onAccepted: root.submit()
                            onTextEdited: root.clearMessage()
                            Keys.onEscapePressed: {
                                clear();
                                showPassword.checked = false;
                                root.clearMessage();
                            }
                            KeyNavigation.tab: showPassword
                            KeyNavigation.backtab: username
                        }
                        PandoraButton {
                            id: showPassword
                            objectName: "showPassword"
                            theme: root.colors
                            onActiveFocusChanged: if (activeFocus) root.reveal(this)
                            width: 88
                            height: password.height
                            enabled: !root.pending
                            checkable: true
                            text: checked ? qsTr("Verbergen") : qsTr("Zeigen")
                            Accessible.name: checked ? qsTr("Passwort verbergen") : qsTr("Passwort anzeigen")
                            KeyNavigation.tab: session
                            KeyNavigation.backtab: password
                        }
                    }
                    Text {
                        objectName: "capsWarning"
                        width: parent.width
                        height: 18
                        text: keyboard.capsLock ? qsTr("Feststelltaste ist aktiv") : ""
                        color: theme.error
                        font.family: "Noto Sans"
                        font.pixelSize: 12
                    }
                }

                Column {
                    width: parent.width
                    spacing: 6
                    Text {
                        text: qsTr("Sitzung")
                        color: theme.secondary
                        font.family: "Noto Sans"
                        font.pixelSize: 13
                    }
                    PandoraComboBox {
                        id: session
                        objectName: "session"
                        theme: root.colors
                        onActiveFocusChanged: if (activeFocus) root.reveal(this)
                        width: parent.width
                        enabled: !root.pending
                        model: sessionModel
                        textRole: "name"
                        currentIndex: sessionModel.lastIndex
                        displayText: currentIndex >= 0 ? currentText
                            : count ? qsTr("Sitzung wählen") : qsTr("Keine Sitzung verfügbar")
                        Accessible.name: qsTr("Sitzung")
                        KeyNavigation.tab: layout
                        KeyNavigation.backtab: showPassword
                    }
                }

                Row {
                    width: parent.width
                    spacing: 12
                    Text {
                        width: 76
                        anchors.verticalCenter: parent.verticalCenter
                        text: qsTr("Tastatur")
                        color: theme.secondary
                        font.family: "Noto Sans"
                        font.pixelSize: 13
                    }
                    PandoraComboBox {
                        id: layout
                        objectName: "layout"
                        theme: root.colors
                        onActiveFocusChanged: if (activeFocus) root.reveal(this)
                        width: parent.width - 88
                        enabled: !root.pending && count > 0
                        model: keyboard.layouts
                        textRole: "longName"
                        currentIndex: keyboard.currentLayout
                        Accessible.name: qsTr("Tastaturlayout")
                        onActivated: index => keyboard.currentLayout = index
                        Connections {
                            target: keyboard
                            function onCurrentLayoutChanged() {
                                layout.currentIndex = keyboard.currentLayout;
                            }
                        }
                        KeyNavigation.tab: login
                        KeyNavigation.backtab: session
                    }
                }

                Text {
                    objectName: "message"
                    width: parent.width
                    height: Math.max(36, implicitHeight)
                    text: root.message
                    color: root.failed ? theme.error : theme.secondary
                    font.family: "Noto Sans"
                    font.pixelSize: 13
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    Accessible.role: Accessible.StaticText
                    Accessible.name: text
                }

                PandoraButton {
                    id: login
                    objectName: "login"
                    theme: root.colors
                    onActiveFocusChanged: if (activeFocus) root.reveal(this)
                    width: parent.width
                    height: 48
                    primary: true
                    text: root.pending ? qsTr("Anmeldung läuft …") : qsTr("Anmelden")
                    enabled: !root.pending && session.count > 0
                    onClicked: root.submit()
                    KeyNavigation.tab: reboot
                    KeyNavigation.backtab: layout
                }

                Row {
                    width: parent.width
                    spacing: 8
                    PandoraButton {
                        id: reboot
                        objectName: "reboot"
                        theme: root.colors
                        onActiveFocusChanged: if (activeFocus) root.reveal(this)
                        width: (parent.width - parent.spacing) / 2
                        text: qsTr("Neustart")
                        enabled: !root.pending && sddm.canReboot
                        onClicked: sddm.reboot()
                        KeyNavigation.tab: shutdown
                        KeyNavigation.backtab: login
                    }
                    PandoraButton {
                        id: shutdown
                        objectName: "shutdown"
                        theme: root.colors
                        onActiveFocusChanged: if (activeFocus) root.reveal(this)
                        width: (parent.width - parent.spacing) / 2
                        text: qsTr("Ausschalten")
                        enabled: !root.pending && sddm.canPowerOff
                        onClicked: sddm.powerOff()
                        KeyNavigation.tab: username
                        KeyNavigation.backtab: reboot
                    }
                }
            }
        }
    }

    Component.onCompleted: focusInput()
}
