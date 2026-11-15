package com.josetron.tidbytmirror;

import android.content.SharedPreferences;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.Socket;
import java.net.URL;
import java.net.URLEncoder;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Talks to the Windows mirror (tools/tidbyt_mirror.py) on the home network. The TV cannot render
 * Tidbyt apps, so an app's options come from the PC, and changed settings go back to it; the PC
 * then publishes them and a fresh picture to GitHub. Only needed while a setting is being changed.
 */
final class PcLink {
    private static final int PORT = 8766;

    private PcLink() {
    }

    /** "http://192.168.x.y:8766" of the PC running the mirror, or null when it is not on. */
    static String find(SharedPreferences prefs) {
        String saved = prefs.getString("pc_address", null);
        if (saved != null && isMirror(saved, 1500)) {
            return "http://" + saved + ":" + PORT;
        }
        final AtomicReference<String> found = new AtomicReference<>();
        ExecutorService pool = Executors.newFixedThreadPool(48);
        for (final String prefix : localPrefixes()) {
            for (int host = 1; host < 255; host++) {
                final String address = prefix + host;
                pool.execute(new Runnable() {
                    @Override
                    public void run() {
                        if (found.get() == null && isMirror(address, 400)) {
                            found.compareAndSet(null, address);
                        }
                    }
                });
            }
        }
        pool.shutdown();
        try {
            pool.awaitTermination(15, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        pool.shutdownNow();
        String address = found.get();
        if (address == null) {
            return null;
        }
        prefs.edit().putString("pc_address", address).apply();
        return "http://" + address + ":" + PORT;
    }

    /** "192.168.68." for each network this TV is on. */
    private static List<String> localPrefixes() {
        List<String> prefixes = new ArrayList<>();
        try {
            for (NetworkInterface nic : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!nic.isUp() || nic.isLoopback()) {
                    continue;
                }
                for (InetAddress address : Collections.list(nic.getInetAddresses())) {
                    if (address instanceof Inet4Address && address.isSiteLocalAddress()) {
                        String text = address.getHostAddress();
                        String prefix = text.substring(0, text.lastIndexOf('.') + 1);
                        if (!prefixes.contains(prefix)) {
                            prefixes.add(prefix);
                        }
                    }
                }
            }
        } catch (Exception e) {
            // no network: nothing to scan
        }
        return prefixes;
    }

    private static boolean isMirror(String address, int timeoutMs) {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(address, PORT), timeoutMs);
        } catch (Exception e) {
            return false;
        }
        try {
            return request("http://" + address + ":" + PORT + "/ping", null).optString("service").equals("tidbyt-mirror");
        } catch (Exception e) {
            return false;
        }
    }

    /** {"ok", "name", "fields": [{id, name, type: text|onoff|choice, value, hint, options}]} */
    static JSONObject schema(String base, String appId) throws Exception {
        return request(base + "/schema?id=" + URLEncoder.encode(appId, "UTF-8"), null);
    }

    static JSONObject save(String base, String appId, JSONObject values) throws Exception {
        JSONObject body = new JSONObject();
        body.put("id", appId);
        body.put("values", values);
        return request(base + "/settings", body);
    }

    private static JSONObject request(String address, JSONObject body) throws Exception {
        HttpURLConnection connection = (HttpURLConnection) new URL(address).openConnection();
        connection.setConnectTimeout(4000);
        connection.setReadTimeout(60000);  // publishing to GitHub takes a few seconds
        try {
            if (body != null) {
                byte[] data = body.toString().getBytes("UTF-8");
                connection.setRequestMethod("POST");
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json");
                try (OutputStream out = connection.getOutputStream()) {
                    out.write(data);
                }
            }
            int code = connection.getResponseCode();
            try (InputStream in = code < 400 ? connection.getInputStream() : connection.getErrorStream()) {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                byte[] buffer = new byte[8192];
                int n;
                while (in != null && (n = in.read(buffer)) > 0) {
                    bytes.write(buffer, 0, n);
                }
                return new JSONObject(new String(bytes.toByteArray(), "UTF-8"));
            }
        } finally {
            connection.disconnect();
        }
    }
}
