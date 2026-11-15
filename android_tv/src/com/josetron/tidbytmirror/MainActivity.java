package com.josetron.tidbytmirror;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ComponentName;
import android.content.DialogInterface;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.InputType;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.EditText;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

/**
 * Tidbyt Mirror for Android TV.
 *
 * Remote, while pictures play:
 *   Left / Right  previous / next app
 *   OK            pause
 *   Down          setup menu: brightness, unlit dots, app names, frame and its thickness, screen saver and its start time, hidden apps
 *   Up            this app's menu: show or hide it on this TV, and its own settings
 *   Back          exit
 * In a menu: Up / Down choose a row, Left / Right change it, OK edits or confirms, Back closes.
 */
public final class MainActivity extends Activity {
    private static final long MENU_CLOSES_MS = 30000;  // the setup menu goes away by itself when left alone
    private static final int NONE = 0, SETUP = 1, APP = 2;
    private static final int SETUP_ROWS = 10, HIDDEN_ROW = 9;
    private static final int[] IDLE_MINUTES = {1, 2, 5, 10, 15, 30, 60};  // choices for when the screen saver starts
    private static final int FRAME_CHOICES = Player.WOODS.length + 1;  // the woods, then "no frame"

    /** One row of the app menu that came from the PC: a text, an on/off switch or a list of choices. */
    private static final class Field {
        String id, name, type, value, hint;
        String[] optionLabels, optionValues;
    }

    private final Handler handler = new Handler(Looper.getMainLooper());
    private LedView view;
    private Player player;
    private SharedPreferences prefs;

    private int menu = NONE;
    private int row;

    // app menu state
    private Feed.Item appItem;
    private boolean appShown;                   // the "Show this app" switch
    private final List<Field> fields = new ArrayList<>();
    private String appStatus;                   // shown instead of the fields while loading, or when the PC is off
    private String pcBase;
    private boolean busy;
    private boolean pausedBefore;

    private final Runnable closeMenu = new Runnable() {
        @Override
        public void run() {
            closeMenus();
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        view = new LedView(this);
        view.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        setContentView(view);
        player = new Player(this, view);
        prefs = player.prefs();
    }

    @Override
    protected void onStart() {
        super.onStart();
        player.applyLook();
        player.start();
    }

    @Override
    protected void onStop() {
        super.onStop();
        handler.removeCallbacks(closeMenu);
        closeMenus();
        player.stop();
    }

    private void closeMenus() {
        handler.removeCallbacks(closeMenu);
        if (menu == APP) {
            player.setPaused(pausedBefore);
            if (appItem != null) {
                player.setHidden(appItem.id, !appShown);
            }
            player.refilter();  // a hidden app leaves the screen now
        }
        menu = NONE;
        view.setMenu(null, null, null, null, 0, null);
    }

    // -- setup menu (Down) --------------------------------------------------

    private int frameChoice() {
        if (!prefs.getBoolean("frame", true)) {
            return Player.WOODS.length;
        }
        return Math.min(Player.WOODS.length - 1, Math.max(0, prefs.getInt("wood", 1)));
    }

    private boolean isScreenSaver() {
        String current = Settings.Secure.getString(getContentResolver(), "screensaver_components");
        return current != null && current.contains(getPackageName() + "/");
    }

    private void showSetup() {
        menu = SETUP;
        int frame = frameChoice();
        int hidden = player.hiddenCount();
        view.setMenu("Tidbyt Mirror setup",
                new String[] {"Screen brightness", "Unlit dots", "Show app name on change", "Frame",
                    "Frame tint", "Frame thickness", "Frame brightness", "Google TV screen saver", "Screen saver starts after", "Hidden apps"},
                new String[] {
                    prefs.getInt("brightness", 70) + "%",
                    prefs.getInt("unlit", 42) == 0 ? "Off" : prefs.getInt("unlit", 42) + "%",
                    prefs.getBoolean("names", false) ? "On" : "Off",
                    frame < Player.WOODS.length ? Player.WOOD_NAMES[frame] : "No frame (full screen)",
                    Player.tintLabel(prefs.getInt("tint_hue", -1)),
                    prefs.getInt("frame_thickness", 70) + "%",
                    prefs.getInt("frame_brightness", 100) + "%",
                    isScreenSaver() ? "On" : "Off",
                    idleLabel(),
                    hidden == 0 ? "None" : hidden + " hidden  (OK: show all)",
                },
                new boolean[] {true, true, true, true, true, true, true, true, true, false},
                row, "Up / Down: choose    Left / Right: change    Back: close");
        handler.removeCallbacks(closeMenu);
        handler.postDelayed(closeMenu, MENU_CLOSES_MS);
    }

    private void changeSetup(int direction) {
        switch (row) {
            case 0: {
                int brightness = Math.min(100, Math.max(20, prefs.getInt("brightness", 70) + 5 * direction));
                prefs.edit().putInt("brightness", brightness).apply();
                break;
            }
            case 1: {
                int unlit = Math.min(100, Math.max(0, prefs.getInt("unlit", 42) + 3 * direction));
                prefs.edit().putInt("unlit", unlit).apply();
                break;
            }
            case 2:
                prefs.edit().putBoolean("names", !prefs.getBoolean("names", false)).apply();
                break;
            case 3: {
                int frame = ((frameChoice() + direction) % FRAME_CHOICES + FRAME_CHOICES) % FRAME_CHOICES;
                SharedPreferences.Editor editor = prefs.edit().putBoolean("frame", frame < Player.WOODS.length);
                if (frame < Player.WOODS.length) {
                    editor.putInt("wood", frame);
                }
                editor.apply();
                break;
            }
            case 4: {
                // Off, then round the colour wheel in small steps, then Off again
                int hue = prefs.getInt("tint_hue", -1) + Player.TINT_STEP * direction;
                if (hue < -Player.TINT_STEP) {
                    hue = 360 - Player.TINT_STEP;
                } else if (hue < 0 || hue >= 360) {
                    hue = -1;
                } else if (hue == Player.TINT_STEP - 1) {
                    hue = 0;  // stepping right from Off (-1) lands on red
                }
                prefs.edit().putInt("tint_hue", hue).apply();
                break;
            }
            case 5: {
                int thickness = Math.min(200, Math.max(20, prefs.getInt("frame_thickness", 70) + 10 * direction));
                prefs.edit().putInt("frame_thickness", thickness).apply();
                break;
            }
            case 6: {
                int level = Math.min(100, Math.max(10, prefs.getInt("frame_brightness", 100) + 5 * direction));
                prefs.edit().putInt("frame_brightness", level).apply();
                break;
            }
            case 7:
                setScreenSaver(!isScreenSaver());
                break;
            case 8:
                changeIdleTime(direction);
                break;
            default:
                break;
        }
        player.applyLook();
        showSetup();
    }

    /** How long the TV waits, idle, before it starts the screen saver (the TV's own setting). */
    private int idleMinutes() {
        int ms = Settings.System.getInt(getContentResolver(), Settings.System.SCREEN_OFF_TIMEOUT, 600000);
        return Math.max(1, Math.round(ms / 60000f));
    }

    private String idleLabel() {
        int minutes = idleMinutes();
        return minutes == 60 ? "1 hour" : minutes + (minutes == 1 ? " minute" : " minutes");
    }

    private void changeIdleTime(int direction) {
        int minutes = idleMinutes(), at = 0;
        for (int i = 0; i < IDLE_MINUTES.length; i++) {
            if (IDLE_MINUTES[i] <= minutes) {
                at = i;
            }
        }
        at = Math.min(IDLE_MINUTES.length - 1, Math.max(0, at + direction));
        try {
            Settings.System.putInt(getContentResolver(), Settings.System.SCREEN_OFF_TIMEOUT, IDLE_MINUTES[at] * 60000);
        } catch (SecurityException e) {
            view.showLabel("Not allowed yet: reinstall from the PC once to allow this");
        }
    }

    /** Makes this app the TV's screen saver, or gives the previous one back. */
    private void setScreenSaver(boolean on) {
        String mine = new ComponentName(this, MirrorDream.class).flattenToString();
        try {
            if (on) {
                String previous = Settings.Secure.getString(getContentResolver(), "screensaver_components");
                if (previous != null && !previous.contains(getPackageName() + "/")) {
                    prefs.edit().putString("previous_screensaver", previous).apply();
                }
                Settings.Secure.putString(getContentResolver(), "screensaver_components", mine);
                Settings.Secure.putInt(getContentResolver(), "screensaver_enabled", 1);
            } else {
                String previous = prefs.getString("previous_screensaver",
                        "com.google.android.apps.tv.dreamx/.service.Backdrop");
                Settings.Secure.putString(getContentResolver(), "screensaver_components", previous);
            }
        } catch (SecurityException e) {
            // Android only lets an app change the screen saver after a one-time permission from a PC:
            // python android_tv/build.py --install grants it.
            view.showLabel("Not allowed yet: reinstall from the PC once to allow this");
        }
    }

    // -- app menu (Up) ------------------------------------------------------

    private void openAppMenu() {
        appItem = player.current();
        if (appItem == null) {
            return;
        }
        menu = APP;
        row = 0;
        appShown = !player.isHidden(appItem.id);
        fields.clear();
        busy = false;
        pausedBefore = player.paused();
        player.setPaused(true);  // hold this app on screen while its menu is open
        appStatus = "Looking for the PC...";
        showApp();

        final String appId = appItem.id;
        new Thread(new Runnable() {
            @Override
            public void run() {
                String status;
                final List<Field> loaded = new ArrayList<>();
                String base = PcLink.find(prefs);
                if (base == null) {
                    status = "To change them, turn on the PC with Tidbyt Mirror running";
                } else {
                    try {
                        JSONObject reply = PcLink.schema(base, appId);
                        if (!reply.optBoolean("ok")) {
                            status = reply.optString("error", "The PC could not read this app's settings");
                        } else {
                            JSONArray list = reply.getJSONArray("fields");
                            for (int i = 0; i < list.length(); i++) {
                                loaded.add(parseField(list.getJSONObject(i)));
                            }
                            status = loaded.isEmpty() ? "This app has no settings" : null;
                        }
                    } catch (Exception e) {
                        status = "The PC did not answer";
                    }
                }
                final String finalStatus = status;
                final String finalBase = base;
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        if (menu != APP || appItem == null || !appItem.id.equals(appId)) {
                            return;
                        }
                        pcBase = finalBase;
                        fields.clear();
                        fields.addAll(loaded);
                        appStatus = finalStatus;
                        showApp();
                    }
                });
            }
        }, "pc-schema").start();
    }

    private static Field parseField(JSONObject json) {
        Field field = new Field();
        field.id = json.optString("id");
        field.name = json.optString("name", field.id);
        field.type = json.optString("type", "text");
        field.value = json.optString("value", "");
        field.hint = json.optString("hint", "");
        JSONArray options = json.optJSONArray("options");
        if (options != null) {
            field.optionLabels = new String[options.length()];
            field.optionValues = new String[options.length()];
            for (int i = 0; i < options.length(); i++) {
                JSONObject option = options.optJSONObject(i);
                field.optionLabels[i] = option == null ? "" : option.optString("label");
                field.optionValues[i] = option == null ? "" : option.optString("value");
            }
        }
        return field;
    }

    /** Rows: "Show this app", then the app's fields (or a status line), then Save (if there are fields). */
    private int appRows() {
        return 1 + (fields.isEmpty() ? 1 : fields.size() + 1);
    }

    private void showApp() {
        int count = appRows();
        String[] labels = new String[count];
        String[] values = new String[count];
        boolean[] arrows = new boolean[count];
        labels[0] = "Show this app on the TV";
        values[0] = appShown ? "On" : "Off";
        arrows[0] = true;
        if (fields.isEmpty()) {
            labels[1] = "Settings";
            values[1] = appStatus == null ? "" : appStatus;
        } else {
            for (int i = 0; i < fields.size(); i++) {
                Field field = fields.get(i);
                labels[i + 1] = field.name;
                if ("onoff".equals(field.type)) {
                    values[i + 1] = "true".equals(field.value) ? "On" : "Off";
                    arrows[i + 1] = true;
                } else if ("choice".equals(field.type)) {
                    values[i + 1] = choiceLabel(field);
                    arrows[i + 1] = true;
                } else {
                    values[i + 1] = field.value.isEmpty() ? "(not set)   OK: edit" : field.value + "   OK: edit";
                }
            }
            labels[count - 1] = busy ? "Saving..." : "Save settings";
            values[count - 1] = busy ? "" : "OK";
        }
        row = Math.min(row, count - 1);
        view.setMenu(appItem.name, labels, values, arrows, row,
                "Up / Down: choose    Left / Right: change    OK: edit or save    Back: close");
        handler.removeCallbacks(closeMenu);  // this menu stays until closed: typing takes time
    }

    private static String choiceLabel(Field field) {
        if (field.optionValues != null) {
            for (int i = 0; i < field.optionValues.length; i++) {
                if (field.optionValues[i].equals(field.value)) {
                    return field.optionLabels[i];
                }
            }
        }
        return field.value;
    }

    private void changeApp(int direction) {
        if (row == 0) {
            appShown = !appShown;
        } else if (!fields.isEmpty() && row <= fields.size()) {
            Field field = fields.get(row - 1);
            if ("onoff".equals(field.type)) {
                field.value = "true".equals(field.value) ? "false" : "true";
            } else if ("choice".equals(field.type) && field.optionValues != null && field.optionValues.length > 0) {
                int at = 0;
                for (int i = 0; i < field.optionValues.length; i++) {
                    if (field.optionValues[i].equals(field.value)) {
                        at = i;
                    }
                }
                int n = field.optionValues.length;
                field.value = field.optionValues[((at + direction) % n + n) % n];
            }
        }
        showApp();
    }

    private void confirmApp() {
        if (row == 0) {
            changeApp(1);
        } else if (!fields.isEmpty() && row <= fields.size()) {
            Field field = fields.get(row - 1);
            if ("text".equals(field.type)) {
                editText(field);
            } else {
                changeApp(1);
            }
        } else if (!fields.isEmpty() && !busy) {
            saveApp();
        }
    }

    /** A text box with the TV's on-screen keyboard. */
    private void editText(final Field field) {
        final EditText input = new EditText(this);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        input.setSingleLine(true);
        input.setText(field.value);
        input.setSelection(field.value.length());
        if (!field.hint.isEmpty()) {
            input.setHint(field.hint);
        }
        new AlertDialog.Builder(this)
                .setTitle(field.name)
                .setMessage(field.hint.isEmpty() ? null : field.hint)
                .setView(input)
                .setPositiveButton("OK", new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface dialog, int which) {
                        field.value = input.getText().toString().trim();
                        if (menu == APP) {
                            showApp();
                        }
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void saveApp() {
        if (pcBase == null || appItem == null) {
            return;
        }
        busy = true;
        showApp();
        final String appId = appItem.id;
        final JSONObject values = new JSONObject();
        try {
            for (Field field : fields) {
                values.put(field.id, field.value);
            }
        } catch (Exception e) {
            // a JSON string never fails to store
        }
        new Thread(new Runnable() {
            @Override
            public void run() {
                String problem = null;
                try {
                    JSONObject reply = PcLink.save(pcBase, appId, values);
                    if (!reply.optBoolean("ok")) {
                        problem = reply.optString("error", "The PC could not save the settings");
                    }
                } catch (Exception e) {
                    problem = "The PC did not answer";
                }
                final String finalProblem = problem;
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        busy = false;
                        if (finalProblem != null) {
                            if (menu == APP) {
                                showApp();
                            }
                            view.showLabel(finalProblem);
                            return;
                        }
                        closeMenus();
                        view.showLabel("Saved. The new picture arrives in about a minute.");
                        player.syncIn(45000);   // the PC needs a moment to publish the new picture
                        player.syncIn(120000);
                        player.syncIn(330000);  // GitHub can serve the old list for up to 5 minutes
                    }
                });
            }
        }, "pc-save").start();
    }

    // -- remote -------------------------------------------------------------

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (menu != NONE) {
            int rows = menu == SETUP ? SETUP_ROWS : appRows();
            switch (keyCode) {
                case KeyEvent.KEYCODE_DPAD_UP:
                    row = (row + rows - 1) % rows;
                    break;
                case KeyEvent.KEYCODE_DPAD_DOWN:
                    row = (row + 1) % rows;
                    break;
                case KeyEvent.KEYCODE_DPAD_LEFT:
                case KeyEvent.KEYCODE_DPAD_RIGHT: {
                    int direction = keyCode == KeyEvent.KEYCODE_DPAD_LEFT ? -1 : 1;
                    if (menu == SETUP) {
                        changeSetup(direction);
                    } else {
                        changeApp(direction);
                    }
                    return true;
                }
                case KeyEvent.KEYCODE_DPAD_CENTER:
                case KeyEvent.KEYCODE_ENTER:
                    if (menu == APP) {
                        confirmApp();
                    } else if (row == HIDDEN_ROW) {
                        player.showAllApps();
                        showSetup();
                    } else {
                        changeSetup(1);
                    }
                    return true;
                case KeyEvent.KEYCODE_BACK:
                case KeyEvent.KEYCODE_MENU:
                    closeMenus();
                    return true;
                default:
                    return super.onKeyDown(keyCode, event);
            }
            if (menu == SETUP) {
                showSetup();
            } else {
                showApp();
            }
            return true;
        }
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_RIGHT:
            case KeyEvent.KEYCODE_MEDIA_NEXT:
                player.next();
                return true;
            case KeyEvent.KEYCODE_DPAD_LEFT:
            case KeyEvent.KEYCODE_MEDIA_PREVIOUS:
                player.previous();
                return true;
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
                player.setPaused(!player.paused());
                return true;
            case KeyEvent.KEYCODE_DPAD_DOWN:
            case KeyEvent.KEYCODE_MENU:
                row = 0;
                showSetup();
                return true;
            case KeyEvent.KEYCODE_DPAD_UP:
                openAppMenu();
                return true;
            default:
                return super.onKeyDown(keyCode, event);
        }
    }
}
