package com.josetron.tidbytmirror;

import android.content.Context;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Movie;
import android.os.Handler;
import android.os.Looper;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * Plays the feed on a LedView: one app after another, about 15 seconds each, like the Tidbyt.
 * Shared by the app's screen (MainActivity) and the screen saver (MirrorDream).
 */
@SuppressWarnings("deprecation")
final class Player {
    static final String[] WOOD_NAMES = {"Dark walnut", "Walnut", "Oak", "Light oak"};
    static final int[] WOODS = {
        Color.rgb(43, 29, 20), Color.rgb(90, 63, 41), Color.rgb(130, 90, 58), Color.rgb(176, 126, 80),
    };
    // Frame tint: a colour mixed into the wood, chosen by its hue (0-350 degrees round the colour
    // wheel, in steps); -1 means no tint.
    static final int TINT_STEP = 10;
    private static final float TINT_STRENGTH = 0.6f;  // how much of the tint colour goes into the wood
    private static final long SHOW_MS = 15000;          // the Tidbyt gives each app about this long
    private static final long MAX_SHOW_MS = 30000;
    private static final long SYNC_EVERY_MS = 5 * 60 * 1000;

    private final Context context;
    private final LedView view;
    private final SharedPreferences prefs;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final List<Feed.Item> all = new ArrayList<>();    // everything in the feed
    private final List<Feed.Item> items = new ArrayList<>();  // what plays: the feed minus hidden apps
    private int index = -1;
    private boolean paused;
    private volatile boolean running;

    private final Runnable advance = new Runnable() {
        @Override
        public void run() {
            show(index + 1);
        }
    };

    private final Runnable syncNow = new Runnable() {
        @Override
        public void run() {
            sync();
        }
    };

    Player(Context context, LedView view) {
        this.context = context;
        this.view = view;
        this.prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE);
        seedSettings();
        applyLook();
    }

    /**
     * First start on a new device: the setup-menu choices of the original TV (Nov 2026), so every
     * install looks the same. Only fills in what is missing, so it never changes a device's own choices.
     */
    private void seedSettings() {
        if (prefs.getBoolean("seeded", false)) {
            return;
        }
        SharedPreferences.Editor edit = prefs.edit();
        String[] ints = {"brightness", "unlit", "frame_thickness", "frame_brightness", "wood", "tint_hue"};
        int[] values = {40, 30, 120, 85, 1, -1};
        for (int i = 0; i < ints.length; i++) {
            if (!prefs.contains(ints[i])) {
                edit.putInt(ints[i], values[i]);
            }
        }
        if (!prefs.contains("frame")) {
            edit.putBoolean("frame", true);
        }
        if (!prefs.contains("hidden")) {
            Set<String> hidden = new HashSet<>();
            for (String id : new String[] {"store:iconote", "store:espn-news", "store:wantedposter",
                    "store:hurricanetracker"}) {
                hidden.add(id);
            }
            edit.putStringSet("hidden", hidden);
        }
        edit.putBoolean("seeded", true).apply();
    }

    SharedPreferences prefs() {
        return prefs;
    }

    /** Brightness, frame and name display, as chosen in the setup menu. */
    void applyLook() {
        view.setBrightness(Math.min(100, Math.max(20, prefs.getInt("brightness", 70))) / 100f);
        view.setUnlit(Math.min(100, Math.max(0, prefs.getInt("unlit", 42))) / 100f);
        view.setFrameThickness(Math.min(200, Math.max(20, prefs.getInt("frame_thickness", 70))) / 100f);
        view.setFramed(prefs.getBoolean("frame", true));
        int wood = WOODS[Math.min(WOODS.length - 1, Math.max(0, prefs.getInt("wood", 1)))];
        int hue = prefs.getInt("tint_hue", -1);
        if (hue >= 0) {
            int tint = Color.HSVToColor(new float[] {hue % 360, 0.75f, 0.75f});
            wood = Color.rgb(mix(Color.red(wood), Color.red(tint)), mix(Color.green(wood), Color.green(tint)),
                    mix(Color.blue(wood), Color.blue(tint)));
        }
        float dim = Math.min(100, Math.max(10, prefs.getInt("frame_brightness", 100))) / 100f;
        wood = Color.rgb((int) (Color.red(wood) * dim), (int) (Color.green(wood) * dim), (int) (Color.blue(wood) * dim));
        view.setWood(wood);
        view.setShowNames(prefs.getBoolean("names", false));
    }

    private static int mix(int wood, int tint) {
        return Math.round(wood + (tint - wood) * TINT_STRENGTH);
    }

    /** "Off", or the tint's colour name with its position on the colour wheel. */
    static String tintLabel(int hue) {
        if (hue < 0) {
            return "Off";
        }
        String[] names = {"Red", "Orange", "Yellow", "Lime", "Green", "Teal", "Blue", "Purple", "Pink", "Red"};
        int[] upTo = {15, 45, 70, 100, 150, 190, 250, 290, 345, 360};
        for (int i = 0; i < upTo.length; i++) {
            if (hue < upTo[i]) {
                return names[i] + "  " + hue + "\u00B0";
            }
        }
        return hue + "\u00B0";
    }

    void start() {
        running = true;
        setAll(Feed.cached(context));  // start with what is already on the TV
        sync();
    }

    void stop() {
        running = false;
        handler.removeCallbacks(advance);
        handler.removeCallbacks(syncNow);
    }

    /** Looks for new pictures after a delay (used after a setting was changed). */
    void syncIn(long delayMs) {
        handler.postDelayed(syncNow, delayMs);
    }

    private void sync() {
        handler.removeCallbacks(syncNow);
        new Thread(new Runnable() {
            @Override
            public void run() {
                final List<Feed.Item> fresh = Feed.sync(context);
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        if (!running) {
                            return;
                        }
                        setAll(fresh);
                        if (all.isEmpty()) {
                            view.setMessage("No pictures yet. Check the internet connection.");
                        }
                        handler.removeCallbacks(syncNow);
                        handler.postDelayed(syncNow, SYNC_EVERY_MS);
                    }
                });
            }
        }, "feed-sync").start();
    }

    private void setAll(List<Feed.Item> fresh) {
        all.clear();
        all.addAll(fresh);
        refilter();
    }

    /** Rebuilds the playing list after the feed or the hidden apps changed. */
    void refilter() {
        Feed.Item current = current();
        String currentId = current == null ? null : current.id;
        String currentVersion = current == null ? null : current.version;
        Set<String> hidden = hidden();
        items.clear();
        for (Feed.Item item : all) {
            if (!hidden.contains(item.id)) {
                items.add(item);
            }
        }
        if (items.isEmpty()) {
            index = -1;
            return;
        }
        int found = -1;
        for (int i = 0; i < items.size(); i++) {
            if (items.get(i).id.equals(currentId)) {
                found = i;
            }
        }
        if (found < 0) {
            show(Math.max(0, index));       // the app on screen is gone or hidden: move on
        } else if (!items.get(found).version.equals(currentVersion)) {
            show(found);                    // its picture changed (a new setting): show it right away
        } else {
            index = found;
        }
    }

    Feed.Item current() {
        return index >= 0 && index < items.size() ? items.get(index) : null;
    }

    void next() {
        show(index + 1);
    }

    void previous() {
        show(index - 1);
    }

    boolean paused() {
        return paused;
    }

    void setPaused(boolean value) {
        paused = value;
        view.setPaused(value);
        schedule();
    }

    private void show(int next) {
        handler.removeCallbacks(advance);
        if (items.isEmpty()) {
            return;
        }
        int count = items.size();
        for (int attempt = 0; attempt < count; attempt++) {  // skip a picture that will not decode
            index = ((next + attempt) % count + count) % count;
            Feed.Item item = items.get(index);
            try {
                byte[] data = Feed.read(item.file);
                Movie movie = Movie.decodeByteArray(data, 0, data.length);
                if (movie != null) {
                    view.setMovie(movie, item.name + "   " + (index + 1) + "/" + count);
                    schedule();
                    return;
                }
            } catch (Exception e) {
                // try the next one
            }
        }
    }

    private void schedule() {
        handler.removeCallbacks(advance);
        if (!paused && running) {
            long length = view.duration();
            handler.postDelayed(advance, Math.min(MAX_SHOW_MS, Math.max(length, SHOW_MS)));
        }
    }

    // -- hidden apps: left out of the rotation on this TV, not removed anywhere -----------------

    private Set<String> hidden() {
        return new HashSet<>(prefs.getStringSet("hidden", new HashSet<String>()));
    }

    boolean isHidden(String id) {
        return hidden().contains(id);
    }

    int hiddenCount() {
        return hidden().size();
    }

    void setHidden(String id, boolean hide) {
        Set<String> hidden = hidden();
        if (hide) {
            hidden.add(id);
        } else {
            hidden.remove(id);
        }
        prefs.edit().putStringSet("hidden", hidden).apply();
    }

    void showAllApps() {
        prefs.edit().remove("hidden").apply();
        refilter();
    }
}
