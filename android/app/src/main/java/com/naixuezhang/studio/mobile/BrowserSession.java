package com.naixuezhang.studio.mobile;

import android.app.Activity;
import android.graphics.Color;
import android.os.Build;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.FrameLayout;
import android.widget.TextView;

import org.json.JSONObject;

import java.net.InetSocketAddress;
import java.net.Proxy;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

final class BrowserSession {
    static final String SITE = "https://aitag.win";
    static final String UA = "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36";

    private static volatile BrowserSession INSTANCE;

    private final Activity activity;
    private final ViewGroup parent;
    private WebView hidden;
    private FrameLayout overlay;
    private final Map<String, Pending> pending = new ConcurrentHashMap<String, Pending>();
    private volatile boolean pageReady;
    private volatile String lastTitle = "";

    static synchronized void attach(Activity activity, ViewGroup parent) {
        if (activity == null || parent == null) return;
        if (INSTANCE != null) {
            if (INSTANCE.activity == activity && INSTANCE.hidden != null) {
                INSTANCE.syncProxy(activity);
                return;
            }
            if (INSTANCE.activity instanceof MainActivity && !INSTANCE.activity.isFinishing() && !INSTANCE.activity.isDestroyed()) {
                return;
            }
            INSTANCE.destroy();
            INSTANCE = null;
        }
        INSTANCE = new BrowserSession(activity, parent);
        INSTANCE.syncProxy(activity);
        INSTANCE.ensureHidden();
        INSTANCE.warmupAsync();
    }

    static BrowserSession get() {
        return INSTANCE;
    }

    static String cookiesFor(String url) {
        try {
            String cookie = CookieManager.getInstance().getCookie(url);
            return cookie == null ? "" : cookie;
        } catch (Exception e) {
            return "";
        }
    }

    private BrowserSession(Activity activity, ViewGroup parent) {
        this.activity = activity;
        this.parent = parent;
    }

    void syncProxy(android.content.Context context) {
        TokenStore tokens = new TokenStore(context);
        Proxy custom = TokenStore.parseProxy(tokens.getProxy());
        applyProxy(custom);
    }

    void warmupAsync() {
        runOnUi(() -> {
            ensureHidden();
            if (hidden != null) hidden.loadUrl(SITE + "/");
            return null;
        }, 8);
    }

    JSONObject fetchJson(String url, int timeoutMs) throws Exception {
        if (!allowedUrl(url)) throw new IllegalStateException("AITag response escaped the fixed HTTPS origin");
        warmupAndWait(Math.min(20000, timeoutMs));
        String id = UUID.randomUUID().toString();
        Pending wait = new Pending();
        pending.put(id, wait);
        String script = "(function(){var id=" + JSONObject.quote(id) + ";var url=" + JSONObject.quote(url)
            + ";(async function(){try{var r=await fetch(url,{credentials:'include',headers:{Accept:'application/json'}});"
            + "var t=await r.text();NaiPipe.done(id, JSON.stringify({ok:r.ok,status:r.status,body:t}));}"
            + "catch(e){NaiPipe.fail(id, String(e));}})();})()";
        runOnUi(() -> {
            ensureHidden();
            hidden.evaluateJavascript(script, null);
            return null;
        }, 8);
        if (!wait.latch.await(Math.max(8000, timeoutMs), TimeUnit.MILLISECONDS)) {
            pending.remove(id);
            throw new IllegalStateException("在线库浏览器通道超时");
        }
        pending.remove(id);
        if (wait.error != null && !wait.error.isEmpty()) {
            throw new IllegalStateException(wait.error);
        }
        JSONObject payload = JsonUtil.obj(wait.json);
        int status = payload.optInt("status", 0);
        String body = payload.optString("body", "");
        if (looksBlocked(status, body)) {
            throw new IllegalStateException("AITag returned HTTP " + (status > 0 ? status : 403));
        }
        if (status < 200 || status >= 300) {
            throw new IllegalStateException("AITag returned HTTP " + status);
        }
        JSONObject parsed = JsonUtil.obj(body);
        if (parsed.length() == 0 && (body == null || body.trim().isEmpty())) {
            throw new IllegalStateException("AITag empty");
        }
        return parsed;
    }

    HttpOutbound.Result fetchBytes(String url, int timeoutMs, int maxBytes) throws Exception {
        if (!allowedUrl(url)) throw new IllegalStateException("AITag image response escaped the fixed origin");
        warmupAndWait(Math.min(20000, timeoutMs));
        String id = UUID.randomUUID().toString();
        Pending wait = new Pending();
        pending.put(id, wait);
        String script = "(function(){var id=" + JSONObject.quote(id) + ";var url=" + JSONObject.quote(url)
            + ";(async function(){try{var r=await fetch(url,{credentials:'include'});"
            + "var buf=await r.arrayBuffer();var bytes=new Uint8Array(buf);"
            + "NaiPipe.begin(id, r.status, r.headers.get('content-type')||'', bytes.length);"
            + "var chunk=24576;for(var i=0;i<bytes.length;i+=chunk){"
            + "var part=bytes.subarray(i, Math.min(i+chunk, bytes.length));"
            + "var s='';for(var j=0;j<part.length;j++)s+=String.fromCharCode(part[j]);"
            + "NaiPipe.chunk(id, btoa(s));}NaiPipe.finish(id);}catch(e){NaiPipe.fail(id, String(e));}})();})()";
        runOnUi(() -> {
            ensureHidden();
            hidden.evaluateJavascript(script, null);
            return null;
        }, 8);
        if (!wait.latch.await(Math.max(8000, timeoutMs), TimeUnit.MILLISECONDS)) {
            pending.remove(id);
            throw new IllegalStateException("在线库图片通道超时");
        }
        pending.remove(id);
        if (wait.error != null && !wait.error.isEmpty()) {
            throw new IllegalStateException(wait.error);
        }
        if (wait.status < 200 || wait.status >= 300) {
            throw new IllegalStateException("AITag image was unavailable");
        }
        byte[] data = wait.bytes();
        if (data.length > maxBytes) throw new IllegalStateException("response exceeded limit");
        return new HttpOutbound.Result(wait.status, data, wait.contentType);
    }

    void showVerify(final Activity host) {
        if (host == null) return;
        host.runOnUiThread(() -> {
            ViewGroup root = (ViewGroup) host.getWindow().getDecorView();
            if (overlay != null && overlay.getParent() != null) {
                ((ViewGroup) overlay.getParent()).removeView(overlay);
            }
            overlay = new FrameLayout(host);
            overlay.setBackgroundColor(0xFF1A1230);
            WebView view = new WebView(host);
            tune(view);
            view.setWebViewClient(new WebViewClient() {
                @Override
                public void onPageFinished(WebView v, String url) {
                    lastTitle = v.getTitle() == null ? "" : v.getTitle();
                    if (url != null && url.contains("aitag.win") && !isChallenge(lastTitle)) {
                        pageReady = true;
                    }
                }
            });
            overlay.addView(view, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            ));
            TextView hint = new TextView(host);
            hint.setText("网站要人机验证时，在这里过完再点返回。");
            hint.setTextColor(0xFFFFF4E8);
            hint.setPadding(28, 28, 28, 8);
            hint.setGravity(Gravity.CENTER_HORIZONTAL);
            FrameLayout.LayoutParams hintLp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            );
            hintLp.topMargin = 48;
            overlay.addView(hint, hintLp);
            Button close = new Button(host);
            close.setText("验证完了，返回");
            close.setTextColor(0xFF2A1230);
            close.setBackgroundColor(0xFFF4D27A);
            FrameLayout.LayoutParams closeLp = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            );
            closeLp.gravity = Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;
            closeLp.bottomMargin = 48;
            overlay.addView(close, closeLp);
            close.setOnClickListener(v -> {
                try {
                    CookieManager.getInstance().flush();
                } catch (Exception ignored) {}
                if (overlay.getParent() instanceof ViewGroup) {
                    ((ViewGroup) overlay.getParent()).removeView(overlay);
                }
                overlay = null;
                warmupAsync();
            });
            root.addView(overlay, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            ));
            view.loadUrl(SITE + "/");
        });
    }

    private void warmupAndWait(int timeoutMs) {
        warmupAsync();
        long deadline = System.currentTimeMillis() + Math.max(4000, timeoutMs);
        while (System.currentTimeMillis() < deadline) {
            if (pageReady && !isChallenge(lastTitle)) return;
            try {
                Thread.sleep(250);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return;
            }
        }
    }

    private void ensureHidden() {
        if (hidden != null) return;
        hidden = new WebView(activity);
        hidden.setVisibility(View.INVISIBLE);
        tune(hidden);
        hidden.addJavascriptInterface(new Pipe(), "NaiPipe");
        hidden.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                lastTitle = view.getTitle() == null ? "" : view.getTitle();
                if (url != null && url.contains("aitag.win") && !isChallenge(lastTitle)) {
                    pageReady = true;
                }
            }
        });
        parent.addView(hidden, new FrameLayout.LayoutParams(1, 1));
    }

    private void tune(WebView view) {
        WebSettings settings = view.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setUserAgentString(UA);
        settings.setMediaPlaybackRequiresUserGesture(false);
        settings.setCacheMode(WebSettings.LOAD_DEFAULT);
        if (Build.VERSION.SDK_INT >= 21) {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        }
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(view, true);
        view.setBackgroundColor(Color.TRANSPARENT);
    }

    private void applyProxy(Proxy proxy) {
        String host = null;
        int port = 0;
        if (proxy != null && proxy.type() != Proxy.Type.DIRECT && proxy.address() instanceof InetSocketAddress) {
            InetSocketAddress address = (InetSocketAddress) proxy.address();
            host = address.getHostString();
            port = address.getPort();
        }
        try {
            Class<?> feature = Class.forName("androidx.webkit.WebViewFeature");
            Class<?> controller = Class.forName("androidx.webkit.ProxyController");
            Class<?> config = Class.forName("androidx.webkit.ProxyConfig");
            Class<?> builder = Class.forName("androidx.webkit.ProxyConfig$Builder");
            String proxyOverride = (String) feature.getField("PROXY_OVERRIDE").get(null);
            boolean supported = (Boolean) feature.getMethod("isFeatureSupported", String.class).invoke(null, proxyOverride);
            if (!supported) return;
            Object instance = controller.getMethod("getInstance").invoke(null);
            if (host == null || port <= 0) {
                controller.getMethod("clearProxyOverride", java.util.concurrent.Executor.class, Runnable.class)
                    .invoke(instance, (java.util.concurrent.Executor) Runnable::run, (Runnable) () -> {});
                return;
            }
            Object b = builder.getDeclaredConstructor().newInstance();
            builder.getMethod("addProxyRule", String.class).invoke(b, host + ":" + port);
            builder.getMethod("addBypassRule", String.class).invoke(b, "127.0.0.1");
            builder.getMethod("addBypassRule", String.class).invoke(b, "localhost");
            Object cfg = builder.getMethod("build").invoke(b);
            controller.getMethod("setProxyOverride", config, java.util.concurrent.Executor.class, Runnable.class)
                .invoke(instance, cfg, (java.util.concurrent.Executor) Runnable::run, (Runnable) () -> {});
        } catch (Throwable ignored) {}
    }

    private <T> T runOnUi(java.util.concurrent.Callable<T> task, int timeoutSec) {
        try {
            if (Looper.myLooper() == Looper.getMainLooper()) {
                return task.call();
            }
            AtomicReference<T> value = new AtomicReference<T>();
            AtomicReference<Exception> error = new AtomicReference<Exception>();
            CountDownLatch latch = new CountDownLatch(1);
            activity.runOnUiThread(() -> {
                try {
                    value.set(task.call());
                } catch (Exception e) {
                    error.set(e);
                } finally {
                    latch.countDown();
                }
            });
            if (!latch.await(timeoutSec, TimeUnit.SECONDS)) {
                throw new IllegalStateException("浏览器通道还没准备好");
            }
            if (error.get() != null) throw error.get();
            return value.get();
        } catch (RuntimeException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException(e.getMessage() == null ? "浏览器通道失败" : e.getMessage());
        }
    }

    private void destroy() {
        try {
            runOnUi(() -> {
                if (hidden != null) {
                    if (hidden.getParent() instanceof ViewGroup) {
                        ((ViewGroup) hidden.getParent()).removeView(hidden);
                    }
                    hidden.destroy();
                    hidden = null;
                }
                return null;
            }, 3);
        } catch (Exception ignored) {}
    }

    static boolean allowedUrl(String url) {
        if (url == null) return false;
        String value = url.toLowerCase(Locale.ROOT);
        return value.startsWith("https://aitag.win/") || value.startsWith("https://ai-img.10118899.xyz/");
    }

    static boolean isChallenge(String title) {
        String text = String.valueOf(title == null ? "" : title).toLowerCase(Locale.ROOT);
        return text.contains("just a moment")
            || (text.contains("moment") && text.contains("cloudflare"))
            || text.contains("checking your browser")
            || text.contains("attention required");
    }

    static boolean looksBlocked(int status, String body) {
        if (status == 403 || status == 503 || status == 429) return true;
        String text = String.valueOf(body == null ? "" : body);
        return text.contains("Just a moment") || text.contains("cf-browser-verification")
            || text.contains("Cloudflare") || text.contains("attention required");
    }

    public final class Pipe {
        @JavascriptInterface
        public void done(String id, String json) {
            Pending wait = pending.get(id);
            if (wait == null) return;
            wait.json = json;
            wait.latch.countDown();
        }

        @JavascriptInterface
        public void fail(String id, String error) {
            Pending wait = pending.get(id);
            if (wait == null) return;
            wait.error = error;
            wait.latch.countDown();
        }

        @JavascriptInterface
        public void begin(String id, int status, String type, int length) {
            Pending wait = pending.get(id);
            if (wait == null) return;
            wait.status = status;
            wait.contentType = type;
            wait.expected = Math.max(0, length);
        }

        @JavascriptInterface
        public void chunk(String id, String b64) {
            Pending wait = pending.get(id);
            if (wait == null || b64 == null) return;
            try {
                wait.chunks.add(android.util.Base64.decode(b64, android.util.Base64.DEFAULT));
            } catch (Exception ignored) {}
        }

        @JavascriptInterface
        public void finish(String id) {
            Pending wait = pending.get(id);
            if (wait == null) return;
            wait.latch.countDown();
        }
    }

    private static final class Pending {
        final CountDownLatch latch = new CountDownLatch(1);
        final List<byte[]> chunks = new ArrayList<byte[]>();
        String json = "";
        String error = "";
        String contentType = "application/octet-stream";
        int status = 0;
        int expected = 0;

        byte[] bytes() {
            int total = 0;
            for (byte[] part : chunks) total += part.length;
            byte[] out = new byte[total];
            int offset = 0;
            for (byte[] part : chunks) {
                System.arraycopy(part, 0, out, offset, part.length);
                offset += part.length;
            }
            return out;
        }
    }
}
