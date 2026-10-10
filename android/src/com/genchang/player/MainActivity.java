package com.genchang.player;

import android.app.Activity;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.OpenableColumns;
import android.util.Log;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * 跟唱助手 · 安卓版
 * 内嵌本地 HTTP 服务，用 WebView 打开 —— 与电脑版共用同一套前端。
 * （刻意不用 lambda，方便直接 javac + d8 构建）
 */
public class MainActivity extends Activity {

    private static final String TAG = "GenChang";
    private static final int REQ_PICK = 4001;

    private WebView web;
    private MiniHttp http;
    private String pendingKind;
    private File staging;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        getWindow().setBackgroundDrawableResource(android.R.color.black);

        staging = new File(getCacheDir(), "staging");
        if (!staging.exists()) staging.mkdirs();

        int port = 0;
        try {
            http = new MiniHttp(this, Songs.dir(this));
            http.start();
            port = http.port();
        } catch (Exception e) {
            Log.e(TAG, "server start failed", e);
            Toast.makeText(this, "本地服务启动失败：" + e.getMessage(), Toast.LENGTH_LONG).show();
        }

        FrameLayout root = new FrameLayout(this);
        web = new WebView(this);
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setMediaPlaybackRequiresUserGesture(false);
        ws.setAllowFileAccess(false);
        ws.setLoadWithOverviewMode(true);
        ws.setUseWideViewPort(false);
        ws.setCacheMode(WebSettings.LOAD_NO_CACHE);
        if (Build.VERSION.SDK_INT >= 21) {
            ws.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        }
        web.setBackgroundColor(0xFF12131A);
        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient());
        web.addJavascriptInterface(new Bridge(), "AndroidApp");
        root.addView(web, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        if (port > 0) web.loadUrl("http://127.0.0.1:" + port + "/");
    }

    @Override
    public void onBackPressed() {
        if (web == null) { super.onBackPressed(); return; }
        web.evaluateJavascript(
                "(function(){try{return window.__onBack?window.__onBack():false}catch(e){return false}})()",
                new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String value) {
                        if (!"true".equals(value)) finish();
                    }
                });
    }

    @Override
    protected void onDestroy() {
        if (http != null) http.stop();
        super.onDestroy();
    }

    // ------------------------------------------------------------------ //
    public class Bridge {

        @JavascriptInterface
        public boolean available() { return true; }

        /** 让用户挑一个声部文件。kind = original | instrumental */
        @JavascriptInterface
        public void pickStem(final String kind) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    pendingKind = kind;
                    Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                    i.addCategory(Intent.CATEGORY_OPENABLE);
                    i.setType("*/*");
                    i.putExtra(Intent.EXTRA_MIME_TYPES,
                            new String[]{"audio/*", "video/*", "application/octet-stream"});
                    i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false);
                    try {
                        startActivityForResult(i, REQ_PICK);
                    } catch (Exception e) {
                        callJs("window.__onPicked && window.__onPicked(" + quote(kind)
                                + ",null," + quote("无法打开文件选择器") + ")");
                    }
                }
            });
        }

        /** 把暂存的两个文件落成一个歌曲包 */
        @JavascriptInterface
        public String commitImport(String songName) {
            try {
                String id = sanitize(songName);
                if (id.length() == 0) id = "我的歌曲";
                File dst = new File(Songs.dir(MainActivity.this), id);
                if (dst.exists()) id = id + "-" + (System.currentTimeMillis() % 10000);
                dst = new File(Songs.dir(MainActivity.this), id);
                dst.mkdirs();

                File srcO = new File(staging, "original");
                File srcI = new File(staging, "instrumental");
                if (!srcI.isFile()) return "{\"ok\":false,\"error\":\"还没选伴奏文件\"}";

                String extO = pickExt(srcO);
                String extI = pickExt(srcI);
                copy(srcO, new File(dst, "original" + extO));
                copy(srcI, new File(dst, "instrumental" + extI));
                srcO.delete();
                srcI.delete();

                long dur = MediaMeta.durationMs(new File(dst, "instrumental" + extI));
                String json = "{\"name\":" + quote(id) + ",\"duration\":" + (dur / 1000.0)
                        + ",\"note\":\"手机导入\",\"stems\":[\"original\",\"instrumental\"]}";
                FileOutputStream fo = new FileOutputStream(new File(dst, "song.json"));
                try {
                    fo.write(json.getBytes("UTF-8"));
                } finally {
                    fo.close();
                }
                String files = "\"files\":{\"original\":" + quote("original" + extO)
                        + ",\"instrumental\":" + quote("instrumental" + extI) + "}";
                return "{\"ok\":true,\"id\":" + quote(id) + "," + files + "}";
            } catch (Exception e) {
                return "{\"ok\":false,\"error\":" + quote(String.valueOf(e.getMessage())) + "}";
            }
        }

        @JavascriptInterface
        public void cancelImport() {
            File[] fs = staging.listFiles();
            if (fs != null) for (File f : fs) f.delete();
        }

        @JavascriptInterface
        public void toast(final String msg) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    Toast.makeText(MainActivity.this, msg, Toast.LENGTH_SHORT).show();
                }
            });
        }
    }

    // ------------------------------------------------------------------ //
    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req != REQ_PICK) return;
        final String kind = pendingKind;
        pendingKind = null;
        if (res != RESULT_OK || data == null || data.getData() == null) {
            callJs("window.__onPicked && window.__onPicked(" + quote(kind) + ",null," + quote("已取消") + ")");
            return;
        }
        Uri uri = data.getData();
        try {
            String name = displayName(uri);
            String ext = extOf(name);
            String stem = (kind == null ? "original" : kind);
            File out = new File(staging, stem);
            InputStream in = getContentResolver().openInputStream(uri);
            try {
                OutputStream os = new FileOutputStream(out);
                try {
                    byte[] b = new byte[1 << 16];
                    int n;
                    while ((n = in.read(b)) > 0) os.write(b, 0, n);
                } finally {
                    os.close();
                }
            } finally {
                in.close();
            }
            FileOutputStream tag = new FileOutputStream(new File(staging, stem + ".ext"));
            try {
                tag.write(ext.getBytes("UTF-8"));
            } finally {
                tag.close();
            }
            callJs("window.__onPicked && window.__onPicked(" + quote(kind) + "," + quote(name) + ",null)");
        } catch (Exception e) {
            Log.e(TAG, "copy failed", e);
            callJs("window.__onPicked && window.__onPicked(" + quote(kind) + ",null,"
                    + quote(String.valueOf(e.getMessage())) + ")");
        }
    }

    private String pickExt(File f) {
        File tag = new File(staging, f.getName() + ".ext");
        if (tag.isFile()) {
            try {
                byte[] b = new byte[(int) tag.length()];
                FileInputStream in = new FileInputStream(tag);
                try {
                    in.read(b);
                } finally {
                    in.close();
                }
                String e = new String(b, "UTF-8").trim();
                if (e.matches("\\.[A-Za-z0-9]{1,5}")) return e.toLowerCase();
            } catch (Exception ignored) {
            }
        }
        return ".m4a";
    }

    private String displayName(Uri uri) {
        String name = null;
        if ("content".equals(uri.getScheme())) {
            Cursor c = null;
            try {
                c = getContentResolver().query(uri, null, null, null, null);
                if (c != null && c.moveToFirst()) {
                    int idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME);
                    if (idx >= 0) name = c.getString(idx);
                }
            } catch (Exception ignored) {
            } finally {
                if (c != null) c.close();
            }
        }
        if (name == null) name = uri.getLastPathSegment();
        return name == null ? "未命名" : name;
    }

    private static String extOf(String n) {
        if (n == null) return ".m4a";
        int d = n.lastIndexOf('.');
        if (d < 0) return ".m4a";
        String e = n.substring(d).toLowerCase();
        return e.matches("\\.[a-z0-9]{1,5}") ? e : ".m4a";
    }

    private static void copy(File a, File b) throws Exception {
        InputStream in = new FileInputStream(a);
        try {
            OutputStream out = new FileOutputStream(b);
            try {
                byte[] buf = new byte[1 << 16];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            } finally {
                out.close();
            }
        } finally {
            in.close();
        }
    }

    private static String sanitize(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if ("\\/:*?\"<>|".indexOf(c) < 0) sb.append(c);
        }
        return sb.toString().trim();
    }

    private static String quote(String s) {
        if (s == null) return "null";
        StringBuilder sb = new StringBuilder("\"");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        return sb.append('"').toString();
    }

    private void callJs(final String js) {
        runOnUiThread(new Runnable() {
            @Override
            public void run() {
                if (web != null) web.evaluateJavascript(js, null);
            }
        });
    }
}
