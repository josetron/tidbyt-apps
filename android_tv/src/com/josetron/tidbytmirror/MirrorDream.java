package com.josetron.tidbytmirror;

import android.service.dreams.DreamService;

/**
 * The screen saver ("dream"): the same picture rotation as the app, shown when the TV is idle.
 * Chosen in the app's setup menu ("Google TV screen saver").
 */
public final class MirrorDream extends DreamService {
    private Player player;

    @Override
    public void onAttachedToWindow() {
        super.onAttachedToWindow();
        setInteractive(false);  // any key on the remote wakes the TV, as a screen saver should
        setFullscreen(true);
        LedView view = new LedView(this);
        setContentView(view);
        player = new Player(this, view);
    }

    @Override
    public void onDreamingStarted() {
        super.onDreamingStarted();
        player.start();
    }

    @Override
    public void onDreamingStopped() {
        player.stop();
        super.onDreamingStopped();
    }
}
