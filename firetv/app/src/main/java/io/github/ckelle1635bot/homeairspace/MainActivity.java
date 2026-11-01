package io.github.ckelle1635bot.homeairspace;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.inputmethod.EditorInfo;
import android.webkit.CookieManager;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.util.Locale;

/**
 * Full-screen wrapper around the Home Airspace website for Fire TV.
 *
 * The first launch asks for the site's address (kept on the device, never in the app),
 * then shows the site in TV mode. Sign-in cookies are kept by the system WebView, so
 * "Remember this device" lasts its full 30 days. The Menu button on the remote offers
 * Reload and Change address; Back leaves the app.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "settings";
    private static final String KEY_ORIGIN = "origin";
    private static final int BACKGROUND = 0xFF0B1420;
    private static final int MINT = 0xFF73DFBA;
    private static final long RETRY_MS = 15_000;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable retry = this::loadHome;
    private WebView web;
    private String origin;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        // Keep the TV awake while the map is open.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        origin = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_ORIGIN, null);
        if (origin == null) showSetup(null);
        else showWeb();
    }

    /**
     * Turns what the user typed into an https origin such as "https://name.onrender.com",
     * or returns null if it is not a usable https address. Any path is dropped.
     */
    static String normalize(String input) {
        if (input == null) return null;
        String text = input.trim();
        if (text.isEmpty()) return null;
        if (!text.contains("://")) text = "https://" + text;
        Uri uri = Uri.parse(text);
        String host = uri.getHost();
        if (!"https".equalsIgnoreCase(uri.getScheme()) || host == null || host.isEmpty()
                || uri.getUserInfo() != null || host.contains(" ")) {
            return null;
        }
        int port = uri.getPort();
        return "https://" + host.toLowerCase(Locale.ROOT) + (port == -1 || port == 443 ? "" : ":" + port);
    }

    private boolean sameOrigin(String url) {
        return origin != null && origin.equals(normalize(url));
    }

    private int dp(float value) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, getResources().getDisplayMetrics()));
    }

    private void showSetup(String current) {
        destroyWeb();
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setGravity(Gravity.CENTER);
        layout.setBackgroundColor(BACKGROUND);
        layout.setPadding(dp(48), dp(32), dp(48), dp(32));

        TextView title = new TextView(this);
        title.setText("Home Airspace");
        title.setTextColor(Color.WHITE);
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 32);
        layout.addView(title);

        TextView help = new TextView(this);
        help.setText("Enter the address of your Home Airspace site, for example your-service.onrender.com");
        help.setTextColor(0xFF99AABD);
        help.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        help.setGravity(Gravity.CENTER);
        help.setPadding(0, dp(12), 0, dp(20));
        layout.addView(help);

        EditText address = new EditText(this);
        address.setSingleLine(true);
        address.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        address.setImeOptions(EditorInfo.IME_ACTION_DONE);
        address.setHint("your-service.onrender.com");
        address.setTextColor(Color.WHITE);
        address.setHintTextColor(0xFF667788);
        address.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        if (current != null) address.setText(current.replaceFirst("^https://", ""));
        layout.addView(address, new LinearLayout.LayoutParams(dp(560), ViewGroup.LayoutParams.WRAP_CONTENT));

        TextView error = new TextView(this);
        error.setTextColor(0xFFFFC079);
        error.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        error.setPadding(0, dp(8), 0, dp(8));
        layout.addView(error);

        Button save = new Button(this);
        save.setText("Save and open");
        save.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        save.setOnClickListener(v -> {
            String value = normalize(address.getText().toString());
            if (value == null) {
                error.setText("That doesn't look like an https web address. Check it and try again.");
                return;
            }
            origin = value;
            getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_ORIGIN, value).apply();
            showWeb();
        });
        address.setOnEditorActionListener((v, actionId, event) -> {
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                save.performClick();
                return true;
            }
            return false;
        });
        layout.addView(save, new LinearLayout.LayoutParams(dp(560), ViewGroup.LayoutParams.WRAP_CONTENT));

        setContentView(layout);
        address.requestFocus();
    }

    private void showWeb() {
        destroyWeb();
        web = new WebView(this);
        web.setBackgroundColor(BACKGROUND);
        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setSaveFormData(false);
        settings.setSupportMultipleWindows(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(web, false);

        web.setWebViewClient(new WebViewClient() {
            @Override
            @SuppressWarnings("deprecation")
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                // Stay on the Home Airspace site; ignore links that lead elsewhere.
                return !sameOrigin(url);
            }

            @Override
            @SuppressWarnings("deprecation")
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                // Called for the main page only, e.g. no internet or the server is waking up.
                showOffline();
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                CookieManager.getInstance().flush();
            }
        });

        web.setFocusable(true);
        web.setFocusableInTouchMode(true);
        setContentView(web);
        web.requestFocus();
        loadHome();
    }

    private void loadHome() {
        handler.removeCallbacks(retry);
        if (web != null && origin != null) web.loadUrl(origin + "/?tv=1");
    }

    private void showOffline() {
        if (web == null) return;
        String page = "<!doctype html><html><body style=\"margin:0;height:100vh;display:flex;align-items:center;"
                + "justify-content:center;background:#0b1420;color:#e9f0f6;font:28px system-ui,sans-serif;text-align:center\">"
                + "<div><div style=\"font-size:40px;font-weight:600\">Home Airspace</div>"
                + "<p style=\"color:#99aabd\">Can't reach the site right now. Trying again shortly&hellip;</p>"
                + "<p style=\"color:#99aabd;font-size:20px\">Press Menu on the remote to change the address.</p></div></body></html>";
        web.loadDataWithBaseURL(null, page, "text/html", "utf-8", null);
        handler.removeCallbacks(retry);
        handler.postDelayed(retry, RETRY_MS);
    }

    private void showMenu() {
        new AlertDialog.Builder(this)
                .setTitle("Home Airspace")
                .setItems(new CharSequence[]{"Reload", "Change site address", "Cancel"}, (dialog, which) -> {
                    if (which == 0) {
                        if (web == null) showWeb();
                        else loadHome();
                    } else if (which == 1) {
                        showSetup(origin);
                    }
                })
                .show();
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_MENU) {
            showMenu();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public void onBackPressed() {
        // Leaving setup without an address returns to the site if one is saved.
        if (web == null && origin != null) showWeb();
        else super.onBackPressed();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) web.onResume();
    }

    @Override
    protected void onPause() {
        CookieManager.getInstance().flush();
        if (web != null) web.onPause();
        super.onPause();
    }

    private void destroyWeb() {
        handler.removeCallbacks(retry);
        if (web != null) {
            CookieManager.getInstance().flush();
            ViewGroup parent = (ViewGroup) web.getParent();
            if (parent != null) parent.removeView(web);
            web.destroy();
            web = null;
        }
    }

    @Override
    protected void onDestroy() {
        destroyWeb();
        super.onDestroy();
    }
}
