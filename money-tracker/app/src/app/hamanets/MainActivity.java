package app.hamanets;

import android.app.Activity;
import android.content.SharedPreferences;
import android.content.res.Configuration;
import android.os.Bundle;
import android.view.HapticFeedbackConstants;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebSettings;
import android.webkit.WebView;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** One screen: a WebView showing the bundled page, plus a small bridge for storage and the NBU rate. */
public class MainActivity extends Activity {
    private static final String RATE_URL =
            "https://bank.gov.ua/NBUStatService/v1/statdirectory/exchange?valcode=EUR&json";

    private WebView web;
    private SharedPreferences prefs;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = getSharedPreferences("hamanets", MODE_PRIVATE);

        boolean dark = (getResources().getConfiguration().uiMode & Configuration.UI_MODE_NIGHT_MASK)
                == Configuration.UI_MODE_NIGHT_YES;

        web = new WebView(this);
        web.setBackgroundColor(getColor(R.color.bg));
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setVerticalScrollBarEnabled(false);
        web.setHapticFeedbackEnabled(true);
        web.setOnLongClickListener(new View.OnLongClickListener() {
            @Override public boolean onLongClick(View v) { return !(web.getHitTestResult().getType() == WebView.HitTestResult.EDIT_TEXT_TYPE); }
        });
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setTextZoom(100);
        s.setSupportZoom(false);
        web.addJavascriptInterface(new Bridge(), "Android");
        setContentView(web);
        web.loadUrl("file:///android_asset/index.html?theme=" + (dark ? "dark" : "light"));
    }

    @Override
    public void onBackPressed() {
        web.evaluateJavascript("window.onBack ? window.onBack() : false", new ValueCallback<String>() {
            @Override public void onReceiveValue(String v) {
                if (!"true".equals(v)) finish();
            }
        });
    }

    private void runJs(final String js) {
        runOnUiThread(new Runnable() {
            @Override public void run() {
                if (!isDestroyed()) web.evaluateJavascript(js, null);
            }
        });
    }

    private void tap() {
        runOnUiThread(new Runnable() {
            @Override public void run() {
                web.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP);
            }
        });
    }

    private void loadRate() {
        new Thread(new Runnable() {
            @Override public void run() {
                String body = null;
                HttpURLConnection c = null;
                try {
                    c = (HttpURLConnection) new URL(RATE_URL).openConnection();
                    c.setConnectTimeout(8000);
                    c.setReadTimeout(8000);
                    if (c.getResponseCode() == 200) {
                        InputStream in = c.getInputStream();
                        ByteArrayOutputStream out = new ByteArrayOutputStream();
                        byte[] buf = new byte[2048];
                        int n;
                        while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                        body = out.toString("UTF-8");
                    }
                } catch (Exception ignored) {
                } finally {
                    if (c != null) c.disconnect();
                }
                runJs("window.onRate(" + (body == null ? "null" : JSONObject.quote(body)) + ")");
            }
        }).start();
    }

    private final class Bridge {
        @JavascriptInterface
        public String load() {
            return prefs.getString("state", "");
        }

        @JavascriptInterface
        public void save(String json) {
            prefs.edit().putString("state", json).apply();
        }

        @JavascriptInterface
        public void haptic() {
            tap();
        }

        @JavascriptInterface
        public void fetchRate() {
            loadRate();
        }
    }
}
