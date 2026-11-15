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
    private static final int[] OFF_RGB = {46, 48, 52};           // an unlit LED at 100%: a faint grey dot
    private static final float FRAME_WOOD = 2.2f;               // wood thickness, in Tidbyt pixels
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
    private float brightness = 0.70f;  // lit LEDs are dimmed to this share: a TV is far brighter than the panel
    private int offColor = Color.rgb(19, 20, 22);  // unlit LEDs, at the level set in the setup menu
    private boolean showNames;         // show the app's name for a moment each time the app changes
    private String menuTitle;          // a menu, when open: a title, then one label and one value per row
    private String[] menuLabels;
    private String[] menuValues;
    private boolean[] menuArrows;      // rows changed with Left / Right get arrows around their value
    private int menuRow;
    private String menuHint;

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
        labelUntil = showNames ? startedAt + 4000 : 0;
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
        if (paused) {
            showLabel(label + "  (paused)");
        } else {
            labelUntil = 0;
            invalidate();
        }
    }

    void setBrightness(float value) {
        brightness = Math.max(0.2f, Math.min(1f, value));
        invalidate();
    }

    /** How visible the unlit LEDs are: 0 = invisible, 1 = the grey of the real panel under room light. */
    void setUnlit(float level) {
        level = Math.max(0f, Math.min(1f, level));
        offColor = Color.rgb((int) (OFF_RGB[0] * level), (int) (OFF_RGB[1] * level), (int) (OFF_RGB[2] * level));
        invalidate();
    }

    void setShowNames(boolean value) {
        showNames = value;
        if (!value) {
            labelUntil = 0;
        }
        invalidate();
    }

    /** Shows a menu (labels == null hides it). */
    void setMenu(String title, String[] labels, String[] values, boolean[] arrows, int selectedRow, String hint) {
        menuTitle = title;
        menuLabels = labels;
        menuValues = values;
        menuArrows = arrows;
        menuRow = selectedRow;
        menuHint = hint;
        invalidate();
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

    /** A menu: a dark card in the middle of the screen, one row per setting (it scrolls when long). */
    private void drawMenu(Canvas canvas, int width, int height) {
        float size = Math.max(22f, height / 30f);
        float rowHeight = size * 2.2f, pad = size * 1.2f;
        int visible = Math.min(menuLabels.length, 9);
        int first = Math.max(0, Math.min(menuRow - visible / 2, menuLabels.length - visible));
        float cardWidth = Math.min(width * 0.72f, size * 38f);
        float cardHeight = pad * 2 + size * 2.2f + rowHeight * visible + size * 1.6f;
        float x = (width - cardWidth) / 2f, y = (height - cardHeight) / 2f;

        fill.setColor(0xE6101418);
        rect.set(x, y, x + cardWidth, y + cardHeight);
        canvas.drawRoundRect(rect, size * 0.6f, size * 0.6f, fill);

        text.setTextSize(size * 1.15f);
        text.setColor(Color.WHITE);
        canvas.drawText(menuTitle == null ? "" : menuTitle, x + pad, y + pad + size, text);
        if (menuLabels.length > visible) {
            String position = (menuRow + 1) + " / " + menuLabels.length;
            text.setTextSize(size * 0.8f);
            text.setColor(Color.rgb(125, 135, 148));
            canvas.drawText(position, x + cardWidth - pad - text.measureText(position), y + pad + size, text);
        }

        text.setTextSize(size);
        float top = y + pad + size * 2.2f;
        for (int n = 0; n < visible; n++) {
            int i = first + n;
            float rowTop = top + n * rowHeight;
            boolean selected = i == menuRow;
            if (selected) {
                fill.setColor(0xFF2A3A4C);
                rect.set(x + pad * 0.5f, rowTop, x + cardWidth - pad * 0.5f, rowTop + rowHeight * 0.9f);
                canvas.drawRoundRect(rect, size * 0.4f, size * 0.4f, fill);
            }
            float baseline = rowTop + rowHeight * 0.9f / 2f + size * 0.35f;
            text.setColor(selected ? Color.WHITE : Color.rgb(170, 180, 190));
            canvas.drawText(menuLabels[i], x + pad, baseline, text);
            String value = menuValues[i] == null ? "" : menuValues[i];
            if (selected && menuArrows != null && menuArrows[i]) {
                value = "\u25C0  " + value + "  \u25B6";
            }
            float room = cardWidth - pad * 2 - text.measureText(menuLabels[i]) - size;
            while (value.length() > 4 && text.measureText(value) > room) {  // long values are cut to fit
                value = value.substring(0, value.length() - 4) + "...";
            }
            canvas.drawText(value, x + cardWidth - pad - text.measureText(value), baseline, text);
        }

        text.setTextSize(size * 0.75f);
        text.setColor(Color.rgb(125, 135, 148));
        canvas.drawText(menuHint == null ? "" : menuHint, x + pad, y + cardHeight - pad * 0.8f, text);
        text.setColor(Color.rgb(200, 208, 216));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        int width = getWidth(), height = getHeight();
        float margin = framed ? FRAME_WOOD + FRAME_GAP : 0f;  // in Tidbyt pixels
        float cell = Math.min(width / (W + 2 * margin), height / (H + 2 * margin));
        if (framed) {
            cell = (float) Math.floor(cell);
        }  // without a frame the panel fills the screen from edge to edge
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
                    dot.setColor(offColor);
                    canvas.drawCircle(left + x * cell + half, cy, unlit, dot);
                } else {
                    dot.setColor(Color.rgb((int) (Color.red(color) * brightness),
                            (int) (Color.green(color) * brightness), (int) (Color.blue(color) * brightness)));
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

        if (menuLabels != null) {
            drawMenu(canvas, width, height);
        }

        if (movie != null && !paused && movie.duration() > 0 || now < labelUntil) {
            postInvalidateDelayed(33);  // about 30 frames a second
        }
    }
}
