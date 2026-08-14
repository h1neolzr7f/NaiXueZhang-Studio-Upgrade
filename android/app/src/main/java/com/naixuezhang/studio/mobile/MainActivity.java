package com.naixuezhang.studio.mobile;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.os.Bundle;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

public class MainActivity extends Activity {
    private WebView webView;

    public class PhoneBridge {
        @JavascriptInterface
        public void openSettings() {
            runOnUiThread(() ->
                startActivity(new Intent(MainActivity.this, SettingsActivity.class))
            );
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
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(0xFF1A1230);
        webView = new WebView(this);
        webView.setBackgroundColor(0xFF1A1230);
        webView.setOverScrollMode(View.OVER_SCROLL_NEVER);
        webView.setVerticalScrollBarEnabled(false);
        webView.setHorizontalScrollBarEnabled(false);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(false);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(false);
        webView.addJavascriptInterface(new PhoneBridge(), "PhoneApp");
        webView.setWebViewClient(new WebViewClient());
        webView.setWebChromeClient(new WebChromeClient());
        root.addView(webView, new FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        ));
        setContentView(root);
        int port = 18797;
        if (getApplication() instanceof StudioApp) {
            port = ((StudioApp) getApplication()).getPort();
        }
        String hash = getIntent() != null ? getIntent().getStringExtra("open_hash") : null;
        if (hash == null || hash.trim().isEmpty()) hash = "";
        else if (!hash.startsWith("#")) hash = "#" + hash;
        webView.loadUrl("http://127.0.0.1:" + port + "/m" + hash);
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
        if (webView != null && webView.canGoBack()) {
            webView.goBack();
            return;
        }
        super.onBackPressed();
    }
}
