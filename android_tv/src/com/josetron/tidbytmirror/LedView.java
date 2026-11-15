package com.josetron.tidbytmirror;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Movie;
import android.graphics.Paint;
import android.graphics.RectF;
import android.os.SystemClock;
import android.view.View;

/**
 * Draws a 64x32 Tidbyt picture the way the real panel looks: one round dot per pixel, faint grey
 * dots where a pixel is off, and (optionally) the wooden frame. Same look as the Windows mirror
 * (tools/tidbyt_mirror.py).
 */
@SuppressWarnings("deprecation")  // android.graphics.Movie: the simplest GIF player with exact frame timing
final class LedView extends View {
    private static final int W = 64;
    private static final int H = 32;
    private static final int OFF_BELOW = 28;                     // brightest channel under this = unlit LED
    private static final int OFF_COLOR = Color.rgb(46, 48, 52);  // an unlit LED: a faint grey dot
    private static final float FRAME_WOOD = 2.2f;                // wood thickness, in Tidbyt pixels
    private static final float FRAME_GAP = 0.8f;                 // black bezel inside the wood

    private final Bitmap frame = Bitmap.createBitmap(W, H, Bitmap.Config.ARGB_8888);
    private final Canvas frameCanvas = new Canvas(frame);
    private final int[] pixels = new int[W * H];
    private final Paint dot = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final RectF rect = new RectF();

    private Movie movie;
    private long startedAt;
    private boolean paused;
    private long pausedAt;
    private boolean framed = true;
    private int wood = Color.rgb(90, 63, 41);
    private String label = "";
    private long labelUntil;
    private String message = "Loading Tidbyt Mirror...";

    LedView(Context context) {
        super(context);
        setBackgroundColor(Color.BLACK);
        text.setColor(Color.rgb(200, 208, 216));
    }

    void setMovie(Movie next, String name) {
        movie = next;
        startedAt = SystemClock.uptimeMillis();
        pausedAt = startedAt;
        label = name == null ? "" : name;
        labelText = paused ? label + "  (paused)" : label;
        labelUntil = startedAt + 4000;
        message = null;
        invalidate();
    }

    void setMessage(String value) {
        if (movie == null) {
            message = value;
            invalidate();
        }
    }

    void setPaused(boolean value) {
        long now = SystemClock.uptimeMillis();
        if (value && !paused) {
            pausedAt = now;
        } else if (!value && paused) {
            startedAt += now - pausedAt;  // carry on from the frame it stopped at
        }
        paused = value;
        showLabel(paused ? label + "  (paused)" : label);
    }

    void setFramed(boolean value) {
        framed = value;
        invalidate();
    }

    void setWood(int color) {
        wood = color;
        invalidate();
    }

    void showLabel(String value) {
        labelText = value;
        labelUntil = SystemClock.uptimeMillis() + 4000;
        invalidate();
    }

    private String labelText;

    /** Length of the current animation in milliseconds (0 for a still picture). */
    int duration() {
        return movie == null ? 0 : movie.duration();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        int width = getWidth(), height = getHeight();
        float margin = framed ? FRAME_WOOD + FRAME_GAP : 0.5f;  // in Tidbyt pixels
        float cell = (float) Math.floor(Math.min(width / (W + 2 * margin), height / (H + 2 * margin)));
        if (cell < 2) {
            return;
        }
        float left = (width - W * cell) / 2f, top = (height - H * cell) / 2f;

        if (framed) {
            float outer = (FRAME_WOOD + FRAME_GAP) * cell, gap = FRAME_GAP * cell;
            fill.setColor(wood);
            rect.set(left - outer, top - outer, left + W * cell + outer, top + H * cell + outer);
            canvas.drawRoundRect(rect, cell * 1.2f, cell * 1.2f, fill);
            fill.setColor(Color.BLACK);
            canvas.drawRect(left - gap, top - gap, left + W * cell + gap, top + H * cell + gap, fill);
        }

        long now = SystemClock.uptimeMillis();
        frame.eraseColor(Color.BLACK);
        if (movie != null) {
            int length = movie.duration();
            long elapsed = (paused ? pausedAt : now) - startedAt;
            movie.setTime(length > 0 ? (int) (elapsed % length) : 0);
            movie.draw(frameCanvas, 0, 0);
        }
        frame.getPixels(pixels, 0, W, 0, 0, W, H);

        float lit = cell * 0.43f, unlit = cell * 0.25f, half = cell / 2f;
        for (int y = 0; y < H; y++) {
            float cy = top + y * cell + half;
            for (int x = 0; x < W; x++) {
                int color = pixels[y * W + x];
                int brightest = Math.max(Color.red(color), Math.max(Color.green(color), Color.blue(color)));
                if (brightest < OFF_BELOW) {
                    dot.setColor(OFF_COLOR);
                    canvas.drawCircle(left + x * cell + half, cy, unlit, dot);
                } else {
                    dot.setColor(color | 0xFF000000);
                    canvas.drawCircle(left + x * cell + half, cy, lit, dot);
                }
            }
        }

        text.setTextSize(Math.max(18f, height / 40f));
        if (message != null) {
            canvas.drawText(message, left + cell, top + H * cell / 2f, text);
        } else if (now < labelUntil && labelText != null && labelText.length() > 0) {
            float size = text.getTextSize();
            float textWidth = text.measureText(labelText);
            fill.setColor(0xC0000000);
            canvas.drawRect(left, top + H * cell - size * 1.8f, left + textWidth + size * 1.2f, top + H * cell, fill);
            canvas.drawText(labelText, left + size * 0.6f, top + H * cell - size * 0.6f, text);
        }

        if (movie != null && !paused && movie.duration() > 0 || now < labelUntil) {
            postInvalidateDelayed(33);  // about 30 frames a second
        }
    }
}
