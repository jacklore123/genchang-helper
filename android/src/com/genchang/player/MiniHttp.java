package com.genchang.player;

import android.content.Context;
import android.content.res.AssetManager;
import android.util.Log;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * 极小的本地 HTTP 服务：把 WebView 界面和歌曲文件用 http://127.0.0.1:port/ 暴露出来，
 * 这样安卓端和电脑端可以共用同一套前端代码（同一份 /api/songs、/media/... 接口）。
 * 支持 Range，保证 <audio> 能拖动进度。
 */
public class MiniHttp {
    private static final String TAG = "GenChang";
    private final Context ctx;
    private final File userSongsDir;
    private ServerSocket server;
    private int port;
    private final ExecutorService pool = Executors.newFixedThreadPool(8);
    private volatile boolean running = true;

    public MiniHttp(Context c, File userSongsDir) {
        this.ctx = c;
        this.userSongsDir = userSongsDir;
    }

    public int port() { return port; }

    public void start() throws IOException {
        server = new ServerSocket(0, 32, InetAddress.getByName("127.0.0.1"));
        port = server.getLocalPort();
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                while (running) {
                    try {
                        final Socket s = server.accept();
                        s.setSoTimeout(20000);
                        pool.execute(new Runnable() {
                            @Override
                            public void run() {
                                try {
                                    handle(s);
                                } catch (Throwable e) {
                                    Log.w(TAG, "conn: " + e);
                                } finally {
                                    try { s.close(); } catch (IOException ignored) {}
                                }
                            }
                        });
                    } catch (IOException e) {
                        if (running) Log.w(TAG, "accept: " + e);
                    }
                }
            }
        }, "genchang-http");
        t.setDaemon(true);
        t.start();
        Log.i(TAG, "MiniHttp on 127.0.0.1:" + port + "  songs=" + userSongsDir);
    }

    public void stop() {
        running = false;
        try { if (server != null) server.close(); } catch (IOException ignored) {}
    }

    // ---------------------------------------------------------------- //
    private void handle(Socket s) throws IOException {
        InputStream in = s.getInputStream();
        String header = readHeader(in);
        if (header == null) return;
        String[] lines = header.split("\r\n");
        String[] first = lines[0].split(" ");
        if (first.length < 2) return;
        String method = first[0];
        String path = URLDecoder.decode(first[1], "UTF-8");
        int q = path.indexOf('?');
        if (q >= 0) path = path.substring(0, q);

        String range = null;
        for (int i = 1; i < lines.length; i++) {
            int c = lines[i].indexOf(':');
            if (c > 0 && lines[i].substring(0, c).trim().equalsIgnoreCase("Range")) {
                range = lines[i].substring(c + 1).trim();
            }
        }
        if ("OPTIONS".equals(method)) { sendSimple(s, 204, "text/plain", new byte[0]); return; }
        if (!"GET".equals(method) && !"HEAD".equals(method)) {
            sendSimple(s, 405, "text/plain", "method not allowed".getBytes(StandardCharsets.UTF_8));
            return;
        }

        try {
            route(s, path, range, "HEAD".equals(method));
        } catch (Exception e) {
            Log.w(TAG, "route " + path + ": " + e);
            sendSimple(s, 500, "text/plain", ("err " + e).getBytes(StandardCharsets.UTF_8));
        }
    }

    private void route(Socket s, String path, final String range, final boolean head) throws IOException {
        if (path.equals("/") || path.equals("/index.html")) {
            final byte[] b = readAsset("ui/index.html");
            if (b == null) { sendSimple(s, 404, "text/plain", "no ui".getBytes()); return; }
            sendSimple(s, 200, "text/html; charset=utf-8", b);
            return;
        }
        if (path.equals("/api/ping")) {
            sendSimple(s, 200, "application/json; charset=utf-8",
                    ("{\"ok\":true,\"app\":\"跟唱助手\",\"platform\":\"android\"}").getBytes(StandardCharsets.UTF_8));
            return;
        }
        if (path.equals("/api/songs")) {
            sendSimple(s, 200, "application/json; charset=utf-8",
                    Songs.listJson(ctx, userSongsDir).getBytes(StandardCharsets.UTF_8));
            return;
        }
        if (path.startsWith("/media/")) {
            String rest = path.substring("/media/".length());
            String[] parts = rest.split("/");
            if (parts.length != 2 || parts[0].contains("..") || parts[1].contains("..")) {
                sendSimple(s, 400, "text/plain", "bad".getBytes()); return;
            }
            Stream src = Songs.open(ctx, userSongsDir, parts[0], parts[1]);
            if (src == null) { sendSimple(s, 404, "text/plain", "not found".getBytes()); return; }
            serveStream(s, src, range, head, parts[1]);
            return;
        }
        if (path.startsWith("/ui/")) {
            byte[] b = readAsset(path.substring(1));
            if (b == null) { sendSimple(s, 404, "text/plain", "not found".getBytes()); return; }
            sendSimple(s, 200, guessType(path), b);
            return;
        }
        sendSimple(s, 404, "text/plain", "not found".getBytes());
    }

    /** 可以用 RandomAccessFile 或 AssetInputStream 提供的音频流。 */
    public static class Stream {
        public long length;
        public RandomAccessFile raf;      // 文件
        public InputStream asset;         // 资源
        public void close() { try { if (raf != null) raf.close(); } catch (Exception ignored) {}
                              try { if (asset != null) asset.close(); } catch (Exception ignored) {} }
    }

    private void serveStream(Socket s, Stream src, String range, boolean head, String name) throws IOException {
        long size = src.length;
        long start = 0, end = size - 1;
        int code = 200;
        if (range != null && range.startsWith("bytes=")) {
            String spec = range.substring(6);
            int dash = spec.indexOf('-');
            try {
                if (dash > 0 && dash < spec.length() - 1) {
                    start = Long.parseLong(spec.substring(0, dash).trim());
                    end = Long.parseLong(spec.substring(dash + 1).trim());
                } else if (dash == 0) {
                    long tail = Long.parseLong(spec.substring(1).trim());
                    start = Math.max(0, size - tail);
                } else {
                    start = Long.parseLong(spec.substring(0, dash).trim());
                }
            } catch (NumberFormatException ignored) {}
            if (start < 0) start = 0;
            if (end >= size) end = size - 1;
            if (start > end) { sendSimple(s, 416, "text/plain", new byte[0]); src.close(); return; }
            code = 206;
        }
        long len = end - start + 1;
        StringBuilder h = new StringBuilder();
        h.append("HTTP/1.1 ").append(code).append(code == 206 ? " Partial Content" : " OK").append("\r\n");
        h.append("Content-Type: ").append(guessType(name)).append("\r\n");
        h.append("Accept-Ranges: bytes\r\n");
        h.append("Content-Length: ").append(len).append("\r\n");
        if (code == 206) h.append("Content-Range: bytes ").append(start).append('-').append(end).append('/').append(size).append("\r\n");
        h.append("Cache-Control: no-store\r\n");
        h.append("Connection: close\r\n\r\n");
        OutputStream out = s.getOutputStream();
        out.write(h.toString().getBytes(StandardCharsets.US_ASCII));
        if (head) { out.flush(); src.close(); return; }

        if (src.raf != null) {
            src.raf.seek(start);
            byte[] buf = new byte[64 * 1024];
            long left = len;
            while (left > 0) {
                int n = src.raf.read(buf, 0, (int) Math.min(buf.length, left));
                if (n <= 0) break;
                out.write(buf, 0, n);
                left -= n;
            }
        } else {
            // 资源流：顺序跳过 start 字节
            long skip = start;
            while (skip > 0) {
                long sk = src.asset.skip(skip);
                if (sk <= 0) { int r = src.asset.read(); if (r < 0) break; skip--; } else skip -= sk;
            }
            byte[] buf = new byte[64 * 1024];
            long left = len;
            while (left > 0) {
                int n = src.asset.read(buf, 0, (int) Math.min(buf.length, left));
                if (n <= 0) break;
                out.write(buf, 0, n);
                left -= n;
            }
        }
        out.flush();
        src.close();
    }

    private void sendSimple(Socket s, int code, String type, byte[] body) throws IOException {
        StringBuilder h = new StringBuilder();
        h.append("HTTP/1.1 ").append(code).append(" X\r\n");
        h.append("Content-Type: ").append(type).append("\r\n");
        h.append("Content-Length: ").append(body.length).append("\r\n");
        h.append("Cache-Control: no-store\r\n");
        h.append("Connection: close\r\n\r\n");
        OutputStream out = s.getOutputStream();
        out.write(h.toString().getBytes(StandardCharsets.US_ASCII));
        out.write(body);
        out.flush();
    }

    private static String guessType(String name) {
        String n = name.toLowerCase();
        if (n.endsWith(".m4a") || n.endsWith(".mp4") || n.endsWith(".aac")) return "audio/mp4";
        if (n.endsWith(".mp3")) return "audio/mpeg";
        if (n.endsWith(".wav")) return "audio/wav";
        if (n.endsWith(".flac")) return "audio/flac";
        if (n.endsWith(".ogg") || n.endsWith(".opus")) return "audio/ogg";
        if (n.endsWith(".html")) return "text/html; charset=utf-8";
        if (n.endsWith(".js")) return "application/javascript; charset=utf-8";
        if (n.endsWith(".css")) return "text/css; charset=utf-8";
        if (n.endsWith(".json")) return "application/json; charset=utf-8";
        if (n.endsWith(".lrc") || n.endsWith(".txt")) return "text/plain; charset=utf-8";
        if (n.endsWith(".png")) return "image/png";
        if (n.endsWith(".svg")) return "image/svg+xml";
        return "application/octet-stream";
    }

    private byte[] readAsset(String path) {
        try (InputStream is = ctx.getAssets().open(path)) {
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            byte[] b = new byte[16384];
            int n;
            while ((n = is.read(b)) > 0) bos.write(b, 0, n);
            return bos.toByteArray();
        } catch (IOException e) { return null; }
    }

    private static String readHeader(InputStream in) throws IOException {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        int state = 0;
        while (bos.size() < 32768) {
            int c = in.read();
            if (c < 0) break;
            bos.write(c);
            if (state == 0 && c == '\r') state = 1;
            else if (state == 1 && c == '\n') state = 2;
            else if (state == 2 && c == '\r') state = 3;
            else if (state == 3 && c == '\n') break;
            else state = 0;
        }
        return bos.size() == 0 ? null : new String(bos.toByteArray(), StandardCharsets.ISO_8859_1);
    }
}
