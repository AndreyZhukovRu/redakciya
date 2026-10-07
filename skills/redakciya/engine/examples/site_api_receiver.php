<?php
/**
 * Приём новостей от навыка «Редакция» по ключу (протокол §9.1). Минимальная основа для самописного сайта.
 *
 *   POST /api/news         Bearer <ключ>, multipart: title, html, excerpt, slug, tags[], categories[], media[]
 *                          → 201 {"id","url"}; повтор с тем же slug → 200 с той же записью
 *   POST /api/news/media   Bearer <ключ>, multipart: file → 201 {"url"}
 *   GET  /api/news/ping    → 200 {"ok":true}
 *   GET  /api/news/<id>    → 200 {"id","url","title"}
 *
 * Ключ — в переменной окружения NEWS_API_KEY или в файле news_api_key рядом со скриптом (вне веб-корня в бою).
 * Хранение — SQLite news.sqlite, файлы — uploads/news/<slug>/. Запуск для проверки:
 *   NEWS_API_KEY=test php -S 127.0.0.1:8099 site_api_receiver.php
 */
declare(strict_types=1);

const BASE = '/api/news';
$dir = __DIR__;
$key = getenv('NEWS_API_KEY') ?: (is_file("$dir/news_api_key") ? trim(file_get_contents("$dir/news_api_key")) : '');
$public = (isset($_SERVER['HTTPS']) ? 'https' : 'http') . '://' . ($_SERVER['HTTP_HOST'] ?? 'localhost');

function out(int $code, array $data): void {
    http_response_code($code);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
if (PHP_SAPI === 'cli-server' && strpos($path, '/uploads/') === 0) {
    return false; // встроенный сервер отдаёт файлы сам
}
if (strpos($path, BASE) !== 0) {
    out(404, ['error' => 'not found']);
}
$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
if ($key === '' || !hash_equals('Bearer ' . $key, $auth)) {
    out(401, ['error' => 'bad key']);
}

$db = new PDO('sqlite:' . $dir . '/news.sqlite');
$db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$db->exec('CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY, slug TEXT UNIQUE, title TEXT, html TEXT,
           excerpt TEXT, tags TEXT, categories TEXT, media TEXT, created_at TEXT)');

function save_file(array $f, string $sub, string $dir, string $public): string {
    if (($f['error'] ?? 1) !== UPLOAD_ERR_OK) {
        out(400, ['error' => 'upload failed']);
    }
    $ext = strtolower(pathinfo($f['name'], PATHINFO_EXTENSION));
    if (!in_array($ext, ['jpg', 'jpeg', 'png', 'webp', 'gif', 'mp4', 'mov'], true)) {
        out(415, ['error' => "type .$ext not allowed"]);
    }
    $target = "$dir/uploads/news/$sub";
    @mkdir($target, 0775, true);
    $name = bin2hex(random_bytes(6)) . ".$ext";
    move_uploaded_file($f['tmp_name'], "$target/$name");
    return "$public/uploads/news/$sub/$name";
}

$rest = trim(substr($path, strlen(BASE)), '/');
$method = $_SERVER['REQUEST_METHOD'];

if ($method === 'GET' && $rest === 'ping') {
    out(200, ['ok' => true]);
}
if ($method === 'POST' && $rest === 'media') {
    out(201, ['url' => save_file($_FILES['file'] ?? [], 'media', $dir, $public)]);
}
if ($method === 'GET' && ctype_digit($rest)) {
    $r = $db->prepare('SELECT id, slug, title FROM news WHERE id = ?');
    $r->execute([(int)$rest]);
    $row = $r->fetch(PDO::FETCH_ASSOC) ?: out(404, ['error' => 'not found']);
    out(200, ['id' => (string)$row['id'], 'url' => "$public/news/{$row['slug']}", 'title' => $row['title']]);
}
if ($method === 'POST' && $rest === '') {
    $slug = preg_replace('~[^a-z0-9-]+~', '-', strtolower($_POST['slug'] ?? ''));
    $title = trim($_POST['title'] ?? '');
    if ($slug === '' || $title === '') {
        out(422, ['error' => 'title and slug required']);
    }
    $r = $db->prepare('SELECT id FROM news WHERE slug = ?');
    $r->execute([$slug]);
    if ($id = $r->fetchColumn()) {
        out(200, ['id' => (string)$id, 'url' => "$public/news/$slug"]);
    }
    $urls = [];
    $files = $_FILES['media'] ?? null;
    if ($files && is_array($files['name'])) {
        foreach ($files['name'] as $i => $n) {
            $urls[] = save_file(['name' => $n, 'tmp_name' => $files['tmp_name'][$i], 'error' => $files['error'][$i]],
                                $slug, $dir, $public);
        }
    }
    $db->prepare('INSERT INTO news (slug, title, html, excerpt, tags, categories, media, created_at)
                  VALUES (?, ?, ?, ?, ?, ?, ?, ?)')
       ->execute([$slug, $title, $_POST['html'] ?? '', $_POST['excerpt'] ?? '',
                  json_encode($_POST['tags'] ?? [], JSON_UNESCAPED_UNICODE),
                  json_encode($_POST['categories'] ?? [], JSON_UNESCAPED_UNICODE),
                  json_encode($urls, JSON_UNESCAPED_SLASHES), date('c')]);
    out(201, ['id' => (string)$db->lastInsertId(), 'url' => "$public/news/$slug"]);
}
out(405, ['error' => 'method not allowed']);
