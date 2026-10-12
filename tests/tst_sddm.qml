import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import QtTest
import "../payload/files/usr/share/sddm/themes/pandora" as Pandora

Item {
    id: scene
    width: 1280
    height: 800

    // Only mocks: the test suite cannot authenticate, reboot or shut down a host.
    QtObject {
        id: sddm
        property bool canReboot: true
        property bool canPowerOff: true
        property int loginCalls: 0
        property int rebootCalls: 0
        property int powerOffCalls: 0
        property string submittedUser: ""
        property string submittedPassword: ""
        property int submittedSession: -1
        signal loginFailed()
        signal loginSucceeded()
        signal informationMessage(string message)
        function login(user, password, session) {
            loginCalls++;
            submittedUser = user;
            submittedPassword = password;
            submittedSession = session;
        }
        function reboot() { rebootCalls++; }
        function powerOff() { powerOffCalls++; }
    }
    QtObject {
        id: userModel
        property string lastUser: "test-user"
    }
    ListModel {
        id: sessionModel
        property int lastIndex: 1
        ListElement { name: "Hyprland" }
        ListElement { name: "Hyprland (uwsm-managed)" }
    }
    QtObject {
        id: keyboard
        property bool capsLock: false
        property int currentLayout: 0
        property list<QtObject> layouts: [
            QtObject { property string longName: "German" },
            QtObject { property string longName: "English (US)" }
        ]
    }
    QtObject {
        id: config
        property url background: Qt.resolvedUrl("../payload/files/usr/share/backgrounds/pandora/wallpaper.png")
    }
    Component {
        id: factory
        Pandora.Main {}
    }

    TestCase {
        name: "PandoraSddm"
        when: windowShown
        property var greeter
        property var username
        property var password
        property var session
        property var login
        property var showPassword

        function initTestCase() {
            failOnWarning(/.*/);
        }

        function init() {
            scene.Window.window.width = 1280;
            scene.Window.window.height = 800;
            sddm.loginCalls = 0;
            sddm.rebootCalls = 0;
            sddm.powerOffCalls = 0;
            sddm.submittedPassword = "";
            sddm.canReboot = true;
            sddm.canPowerOff = true;
            userModel.lastUser = "test-user";
            sessionModel.lastIndex = 1;
            keyboard.currentLayout = 0;
            keyboard.capsLock = false;
            greeter = createTemporaryObject(factory, scene);
            verify(greeter !== null);
            username = findChild(greeter, "username");
            password = findChild(greeter, "password");
            session = findChild(greeter, "session");
            login = findChild(greeter, "login");
            showPassword = findChild(greeter, "showPassword");
            waitForRendering(greeter);
        }

        function test_rememberedDefaults() {
            compare(username.text, "test-user");
            compare(session.currentIndex, 1);
            compare(password.echoMode, TextInput.Password);
            verify(password.activeFocus);
            compare(findChild(greeter, "layout").currentText, "German");
        }

        function test_emptyFieldsDoNotAuthenticate() {
            username.text = "  ";
            greeter.submit();
            compare(sddm.loginCalls, 0);
            verify(username.activeFocus);
            username.text = "test-user";
            greeter.submit();
            compare(sddm.loginCalls, 0);
            verify(password.activeFocus);
            verify(greeter.failed);
        }

        function test_loginAndRetry() {
            username.text = " test-user ";
            password.text = "test-only";
            session.currentIndex = 0;
            greeter.submit();
            compare(sddm.loginCalls, 1);
            compare(sddm.submittedUser, "test-user");
            compare(sddm.submittedPassword, "test-only");
            compare(sddm.submittedSession, 0);
            verify(greeter.pending);
            verify(!password.enabled);
            greeter.submit();
            compare(sddm.loginCalls, 1);
            sddm.loginFailed();
            verify(!greeter.pending);
            verify(greeter.failed);
            compare(password.text, "");
            verify(password.activeFocus);
            password.text = "test-only";
            greeter.submit();
            compare(sddm.loginCalls, 2);
            sddm.loginSucceeded();
            compare(password.text, "");
            verify(!greeter.failed);
            verify(greeter.pending);
        }

        function test_enterAndPasswordVisibility() {
            password.forceActiveFocus();
            password.text = "test-only";
            mouseClick(showPassword);
            compare(password.echoMode, TextInput.Normal);
            password.forceActiveFocus();
            keyClick(Qt.Key_Return);
            compare(sddm.loginCalls, 1);
            sddm.loginFailed();
            compare(password.echoMode, TextInput.Password);
            password.text = "test-only";
            keyClick(Qt.Key_Escape);
            compare(password.text, "");
        }

        function test_keyboardNavigationAndLayout() {
            username.forceActiveFocus();
            keyClick(Qt.Key_Tab);
            verify(password.activeFocus);
            keyClick(Qt.Key_Tab);
            verify(showPassword.activeFocus);
            keyClick(Qt.Key_Tab);
            verify(session.activeFocus);
            keyClick(Qt.Key_Tab);
            const layout = findChild(greeter, "layout");
            verify(layout.activeFocus);
            layout.currentIndex = 1;
            layout.activated(1);
            compare(keyboard.currentLayout, 1);
            keyboard.currentLayout = 0;
            compare(layout.currentIndex, 0);
            keyboard.capsLock = true;
            verify(findChild(greeter, "capsWarning").text.length > 0);
        }

        function test_messagesAndPowerCapabilities() {
            sddm.informationMessage("<b>PAM information</b>");
            const message = findChild(greeter, "message");
            compare(message.textFormat, Text.PlainText);
            compare(message.text, "<b>PAM information</b>");
            const reboot = findChild(greeter, "reboot");
            const shutdown = findChild(greeter, "shutdown");
            sddm.canReboot = false;
            sddm.canPowerOff = false;
            verify(!reboot.enabled);
            verify(!shutdown.enabled);
            sddm.canReboot = true;
            sddm.canPowerOff = true;
            mouseClick(reboot);
            mouseClick(shutdown);
            compare(sddm.rebootCalls, 1);
            compare(sddm.powerOffCalls, 1);
        }

        function test_sessionPopupSelection() {
            session.forceActiveFocus();
            keyClick(Qt.Key_Space);
            tryCompare(session.popup, "visible", true);
            keyClick(Qt.Key_Up);
            keyClick(Qt.Key_Return);
            compare(session.currentIndex, 0);
            verify(!session.popup.visible);
        }

        function test_noSessionsDoNotAuthenticate() {
            session.model = [];
            password.text = "test-only";
            verify(!login.enabled);
            greeter.submit();
            compare(sddm.loginCalls, 0);
            verify(greeter.failed);
        }

        function test_smallScreenIsScrollable() {
            greeter.width = 640;
            greeter.height = 480;
            const scroll = findChild(greeter, "viewport");
            verify(scroll.contentHeight > scroll.height);
            verify(login.width > 200);
            username.forceActiveFocus();
            for (let i = 0; i < 5; ++i)
                keyClick(Qt.Key_Tab);
            verify(login.activeFocus);
            verify(scroll.contentY > 0);
            const position = login.mapToItem(scroll, 0, 0);
            verify(position.y >= 0);
            verify(position.y + login.height <= scroll.height);
        }
    }
}
