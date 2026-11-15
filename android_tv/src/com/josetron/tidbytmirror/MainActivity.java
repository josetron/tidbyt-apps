package com.josetron.tidbytmirror;

import android.app.Activity;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.Movie;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.view.View;
import android.view.WindowManager;

import java.util.ArrayList;
import java.util.List;

/**
 * Tidbyt Mirror for Android TV. Plays the Tidbyt apps one after another, about 15 seconds each,
 * like the device does.
 *
 * Remote: Left / Right = previous / next app, OK = pause, Up = frame on/off,
 * Down = frame shade, Back = exit.
 */
@SuppressWarnings("deprecation")
public final class MainActivity extends Activity {
    private static final long SHOW_MS = 15000;          // the Tidbyt gives each app about this long
    private static final long MAX_SHOW_MS = 30000;
    private static final long SYNC_EVERY_MS = 5 * 60 * 1000;
    private static final int[] WOODS = {                // frame shades, dark walnut to light oak
        Color.rgb(43, 29, 20), Color.rgb(90, 63, 41), Color.rgb(130, 90, 58), Color.rgb(176, 126, 80),
    };

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final List<Feed.Item> items = new ArrayList<>();
    private LedView view;
    private SharedPreferences prefs;
    private int index = -1;
    private boolean paused;
    private boolean framed;
    private int woodIndex;
    private volatile boolean running;

    private final Runnable advance = new Runnable() {
        @Override
        public void run() {
            show(index + 1);
        }
    };

    private final Runnable syncLater = new Runnable() {
        @Override
        public void run() {
            sync();
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        prefs = getSharedPreferences("settings", MODE_PRIVATE);
        framed = prefs.getBoolean("frame", true);
        woodIndex = Math.min(WOODS.length - 1, Math.max(0, prefs.getInt("wood", 1)));

        view = new LedView(this);
        view.setFramed(framed);
        view.setWood(WOODS[woodIndex]);
        view.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
        setContentView(view);
    }

    @Override
    protected void onStart() {
        super.onStart();
        running = true;
        setItems(Feed.cached(this));  // start with what is already on the TV
        sync();
    }

    @Override
    protected void onStop() {
        super.onStop();
        running = false;
        handler.removeCallbacks(advance);
        handler.removeCallbacks(syncLater);
    }

    /** Refreshes the feed on a background thread, now and then every few minutes. */
    private void sync() {
        handler.removeCallbacks(syncLater);
        new Thread(new Runnable() {
            @Override
            public void run() {
                final List<Feed.Item> fresh = Feed.sync(MainActivity.this);
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        if (!running) {
                            return;
                        }
                        setItems(fresh);
                        if (items.isEmpty()) {
                            view.setMessage("No pictures yet. Check the internet connection.");
                        }
                        handler.postDelayed(syncLater, SYNC_EVERY_MS);
                    }
                });
            }
        }, "feed-sync").start();
    }

    private void setItems(List<Feed.Item> fresh) {
        String currentId = index >= 0 && index < items.size() ? items.get(index).id : null;
        items.clear();
        items.addAll(fresh);
        if (items.isEmpty()) {
            return;
        }
        int found = -1;
        for (int i = 0; i < items.size(); i++) {
            if (items.get(i).id.equals(currentId)) {
                found = i;
            }
        }
        if (found >= 0) {
            index = found;       // keep playing the same app; its new picture shows next time round
        } else {
            show(0);
        }
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
        if (!paused) {
            long length = view.duration();
            handler.postDelayed(advance, Math.min(MAX_SHOW_MS, Math.max(length, SHOW_MS)));
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        switch (keyCode) {
            case KeyEvent.KEYCODE_DPAD_RIGHT:
            case KeyEvent.KEYCODE_MEDIA_NEXT:
                show(index + 1);
                return true;
            case KeyEvent.KEYCODE_DPAD_LEFT:
            case KeyEvent.KEYCODE_MEDIA_PREVIOUS:
                show(index - 1);
                return true;
            case KeyEvent.KEYCODE_DPAD_CENTER:
            case KeyEvent.KEYCODE_ENTER:
            case KeyEvent.KEYCODE_MEDIA_PLAY_PAUSE:
                paused = !paused;
                view.setPaused(paused);
                schedule();
                return true;
            case KeyEvent.KEYCODE_DPAD_UP:
                framed = !framed;
                view.setFramed(framed);
                prefs.edit().putBoolean("frame", framed).apply();
                return true;
            case KeyEvent.KEYCODE_DPAD_DOWN:
                woodIndex = (woodIndex + 1) % WOODS.length;
                view.setWood(WOODS[woodIndex]);
                prefs.edit().putInt("wood", woodIndex).apply();
                return true;
            default:
                return super.onKeyDown(keyCode, event);
        }
    }
}
