package app.tgfinder;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ContentValues;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.provider.MediaStore;
import android.view.KeyEvent;
import android.view.ViewGroup;
import android.webkit.URLUtil;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.URL;

public class MainActivity extends Activity {
    private static final String BASE = "http://127.0.0.1:" + FinderService.PORT + "/";
    private WebView web;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 1);
        }
        Intent svc = new Intent(this, FinderService.class);
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(svc); else startService(svc);

        web = new WebView(this);
        setContentView(web, new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                if ("127.0.0.1".equals(u.getHost())) return false;
                openExternal(u);
                return true;
            }
        });
        web.setDownloadListener((url, ua, disposition, mime, len) -> save(url, URLUtil.guessFileName(url, disposition, mime), mime));
        web.loadData("<body style='font:18px sans-serif;text-align:center;padding-top:40vh;color:#888'>Starting Telegram Finder…</body>", "text/html", "utf-8");
        new Thread(this::waitForServer, "wait-server").start();
    }

    private void waitForServer() {
        for (int i = 0; i < 240; i++) {
            try (Socket sock = new Socket()) {
                sock.connect(new InetSocketAddress("127.0.0.1", FinderService.PORT), 500);
                runOnUiThread(() -> web.loadUrl(BASE));
                return;
            } catch (Exception e) {
                try {
                    Thread.sleep(500);
                } catch (InterruptedException ie) {
                    return;
                }
            }
        }
        runOnUiThread(() -> Toast.makeText(this, "The search engine did not start", Toast.LENGTH_LONG).show());
    }

    private void openExternal(Uri u) {
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, u).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, "No app can open " + u, Toast.LENGTH_LONG).show();
        }
    }

    /** Export files are served by the local engine; copy them into the Downloads folder. */
    private void save(String url, String name, String mime) {
        new Thread(() -> {
            String where;
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                try (InputStream in = c.getInputStream(); OutputStream out = openTarget(name, mime)) {
                    byte[] buf = new byte[65536];
                    for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
                }
                where = "Saved " + name + (Build.VERSION.SDK_INT >= 29 ? " to Downloads" : " to the app's files folder");
            } catch (Exception e) {
                where = "Could not save: " + e.getMessage();
            }
            final String msg = where;
            runOnUiThread(() -> Toast.makeText(this, msg, Toast.LENGTH_LONG).show());
        }, "export").start();
    }

    private OutputStream openTarget(String name, String mime) throws Exception {
        if (Build.VERSION.SDK_INT >= 29) {
            ContentValues v = new ContentValues();
            v.put(MediaStore.Downloads.DISPLAY_NAME, name);
            v.put(MediaStore.Downloads.MIME_TYPE, mime == null ? "application/octet-stream" : mime.split(";")[0]);
            Uri uri = getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, v);
            return getContentResolver().openOutputStream(uri);
        }
        return new FileOutputStream(new File(getExternalFilesDir(Environment.DIRECTORY_DOWNLOADS), name));
    }

    @Override
    public boolean onKeyDown(int key, KeyEvent e) {
        if (key == KeyEvent.KEYCODE_BACK) {
            moveTaskToBack(true);  // keep searches running; "Quit" is in the notification
            return true;
        }
        return super.onKeyDown(key, e);
    }
}
