package com.josetron.tidbytmirror;

import android.content.Context;
import android.content.SharedPreferences;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * The picture feed: manifest.json plus one GIF per Tidbyt app, published every 15 minutes by
 * GitHub Actions to the mirror-feed branch. Files are kept on the TV, so the last pictures still
 * play when the network is down.
 */
final class Feed {
    static final String BASE = "https://raw.githubusercontent.com/josetron/tidbyt-apps/mirror-feed/";

    static final class Item {
        String id;
        String name;
        String version;
        boolean store;
        File file;
        long minuteStart;                 // clock apps: a picture per minute, the first at this Unix time
        List<File> minuteFiles = new ArrayList<>();

        /** The picture to show now: for a clock, the one drawn for the current minute. */
        File fileNow() {
            long i = System.currentTimeMillis() / 60000 - minuteStart / 60;
            return i >= 0 && i < minuteFiles.size() ? minuteFiles.get((int) i) : file;
        }
    }

    private Feed() {
    }

    private static File dir(Context context) {
        File dir = new File(context.getFilesDir(), "feed");
        //noinspection ResultOfMethodCallIgnored
        dir.mkdirs();
        return dir;
    }

    /** Downloads whatever changed and returns the apps that can be played, in the device's order. */
    static List<Item> sync(Context context) {
        File dir = dir(context);
        File manifestFile = new File(dir, "manifest.json");
        try {
            byte[] fresh = download(BASE + "manifest.json?t=" + System.currentTimeMillis() / 60000);
            new JSONObject(new String(fresh, "UTF-8"));  // only keep it if it parses
            write(manifestFile, fresh);
        } catch (Exception e) {
            // offline or GitHub unreachable: fall back to the manifest saved last time
        }
        return load(context, true);
    }

    /** The apps already on the TV, without touching the network. */
    static List<Item> cached(Context context) {
        return load(context, false);
    }

    private static List<Item> load(Context context, boolean fetch) {
        List<Item> items = new ArrayList<>();
        File dir = dir(context);
        File manifestFile = new File(dir, "manifest.json");
        if (!manifestFile.exists()) {
            return items;
        }
        SharedPreferences versions = context.getSharedPreferences("feed_versions", Context.MODE_PRIVATE);
        Set<String> wanted = new HashSet<>();
        wanted.add("manifest.json");
        try {
            JSONArray apps = new JSONObject(new String(read(manifestFile), "UTF-8")).getJSONArray("apps");
            for (int i = 0; i < apps.length(); i++) {
                JSONObject app = apps.getJSONObject(i);
                Item item = new Item();
                item.id = app.getString("id");
                item.name = app.optString("name", item.id);
                item.version = app.optString("version", "");
                item.store = app.optBoolean("store", false);
                String fileName = app.getString("file");
                if (fileName.contains("/") || fileName.contains("\\")) {
                    continue;  // file names only
                }
                item.file = new File(dir, fileName);
                wanted.add(fileName);

                boolean current = item.file.exists() && item.version.equals(versions.getString(fileName, null));
                if (!current && fetch) {
                    try {
                        File tmp = new File(dir, fileName + ".tmp");
                        write(tmp, download(BASE + fileName + "?v=" + item.version));
                        if (tmp.renameTo(item.file) || (item.file.delete() && tmp.renameTo(item.file))) {
                            versions.edit().putString(fileName, item.version).apply();
                        }
                    } catch (Exception e) {
                        // keep the older picture, if there is one
                    }
                }
                JSONArray minutes = app.optJSONArray("minute_files");
                if (minutes != null) {
                    item.minuteStart = app.optLong("minute_start", 0);
                    String minuteVersion = String.valueOf(item.minuteStart);
                    for (int m = 0; m < minutes.length(); m++) {
                        String name = minutes.getString(m);
                        if (name.contains("/") || name.contains("\\")) {
                            break;
                        }
                        File f = new File(dir, name);
                        wanted.add(name);
                        if (fetch && !(f.exists() && minuteVersion.equals(versions.getString(name, null)))) {
                            try {
                                write(f, download(BASE + name + "?v=" + minuteVersion));
                                versions.edit().putString(name, minuteVersion).apply();
                            } catch (Exception e) {
                                break;  // the rest would fail too; the main picture still plays
                            }
                        }
                        if (!f.exists()) {
                            break;
                        }
                        item.minuteFiles.add(f);
                    }
                }
                if (item.file.exists()) {
                    items.add(item);
                }
            }
        } catch (Exception e) {
            return items;
        }
        if (fetch) {  // forget pictures of apps that left the feed
            File[] files = dir.listFiles();
            if (files != null) {
                for (File f : files) {
                    if (!wanted.contains(f.getName())) {
                        //noinspection ResultOfMethodCallIgnored
                        f.delete();
                    }
                }
            }
        }
        return items;
    }

    static byte[] read(File file) throws Exception {
        try (InputStream in = new FileInputStream(file)) {
            return readAll(in);
        }
    }

    private static void write(File file, byte[] data) throws Exception {
        try (FileOutputStream out = new FileOutputStream(file)) {
            out.write(data);
        }
    }

    private static byte[] download(String address) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        connection.setConnectTimeout(15000);
        connection.setReadTimeout(30000);
        connection.setRequestProperty("User-Agent", "TidbytMirrorTV/1.0");
        try {
            if (connection.getResponseCode() != 200) {
                throw new Exception("HTTP " + connection.getResponseCode());
            }
            try (InputStream in = connection.getInputStream()) {
                return readAll(in);
            }
        } finally {
            connection.disconnect();
        }
    }

    private static byte[] readAll(InputStream in) throws Exception {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[16384];
        int n;
        while ((n = in.read(buffer)) > 0) {
            out.write(buffer, 0, n);
        }
        return out.toByteArray();
    }
}
