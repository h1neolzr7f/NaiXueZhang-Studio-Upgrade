package com.naixuezhang.studio.mobile;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

public class MainActivity extends Activity {
    private WebView webView;
    private int port = 18797;
    private int loadTries = 0;

    public class PhoneApp {
        @JavascriptInterface
        public void openSettings() {
            runOnUiThread(() ->
                startActivity(new Intent(MainActivity.this, SettingsActivity.class))
            );
        }

        @JavascriptInterface
        public void retry() {
            runOnUiThread(() -> loadStudio(""));
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        getWindow().setStatusBarColor(0xFF1A1230);
        getWindow().setNavigationBarColor(0xFF120C22);
        if (Build.VERSION.SDK_INT >= 29) {
            getWindow().setNavigationBarContrastEnforced(false);
        }
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFF1A1230);
        root.setFitsSystemWindows(true);
        webView = new WebView(this);
        webView.setBackgroundColor(0xFF1A1230);
        webView.setOverScrollMode(View.OVER_SCROLL_NEVER);
        webView.setVerticalScrollBarEnabled(false);
        webView.setHorizontalScrollBarEnabled(false);
        webView.setLayerType(View.LAYER_TYPE_HARDWARE, null);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setTextZoom(100);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        if (Build.VERSION.SDK_INT >= 21) {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        }
        webView.addJavascriptInterface(new PhoneApp(), "PhoneApp");
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleUrl(request != null ? request.getUrl() : null);
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleUrl(url == null ? null : Uri.parse(url));
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request != null && request.isForMainFrame()) {
                    showRetry(error == null ? "页面打不开" : String.valueOf(error.getDescription()));
                }
            }

            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                showRetry(description);
            }
        });
        webView.setWebChromeClient(new WebChromeClient());
        root.addView(webView, new FrameLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT,
            ViewGroup.LayoutParams.MATCH_PARENT
        ));
        setContentView(root);
        if (getApplication() instanceof StudioApp) {
            port = ((StudioApp) getApplication()).getPort();
        }
        String hash = getIntent() != null ? getIntent().getStringExtra("open_hash") : null;
        loadStudio(hash);
    }

    private boolean handleUrl(Uri uri) {
        if (uri == null) return false;
        String host = uri.getHost();
        if ("127.0.0.1".equals(host) || "localhost".equals(host)) return false;
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (Exception ignored) {}
        return true;
    }

    private void loadStudio(String hash) {
        if (hash == null || hash.trim().isEmpty()) hash = "";
        else if (!hash.startsWith("#")) hash = "#" + hash;
        final String suffix = hash;
        webView.setBackgroundColor(0xFF1A1230);
        webView.loadUrl("http://127.0.0.1:" + port + "/m" + suffix);
        if (loadTries < 8) {
            loadTries += 1;
            webView.postDelayed(() -> {
                if (webView.getTitle() == null || webView.getTitle().isEmpty()) {
                    webView.loadUrl("http://127.0.0.1:" + port + "/m" + suffix);
                }
            }, 600);
        }
    }

    private void showRetry(String reason) {
        String safe = String.valueOf(reason == null ? "本机服务还没起来" : reason)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
        String html = "<!doctype html><html><head><meta charset='utf-8'>"
            + "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            + "<style>body{margin:0;background:#1a1230;color:#fff4e8;font:16px/1.6 sans-serif;padding:32px 22px}"
            + "button{margin-top:16px;border:0;border-radius:999px;padding:12px 18px;"
            + "background:linear-gradient(135deg,#ff8fb8,#f4d27a);color:#2a1230;font-weight:700}</style></head>"
            + "<body><h2>还没打开</h2><p>这是手机本地应用，不连电脑。再试一次即可。</p>"
            + "<p style='color:#b8a8c9'>" + safe + "</p>"
            + "<button onclick='PhoneApp.retry()'>重试</button></body></html>";
        webView.loadDataWithBaseURL("http://127.0.0.1:" + port + "/", html, "text/html", "utf-8", null);
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (webView != null) {
            webView.evaluateJavascript(
                "(function(){ if (window.__NAI_REFRESH__) window.__NAI_REFRESH__(); })()",
                null
            );
        }
    }

    @Override
    public void onBackPressed() {
        if (webView == null) {
            super.onBackPressed();
            return;
        }
        webView.evaluateJavascript("(function(){return location.hash||'';})()", value -> {
            String hash = String.valueOf(value == null ? "" : value).replace("\"", "");
            if (hash.contains("/work") || hash.contains("/batch") || hash.contains("/gallery")
                || hash.contains("/settings") || hash.contains("/pipeline") || hash.contains("/pair")) {
                webView.loadUrl("http://127.0.0.1:" + port + "/m#/browse");
                return;
            }
            if (webView.canGoBack()) {
                webView.goBack();
                return;
            }
            finish();
        });
    }
}
