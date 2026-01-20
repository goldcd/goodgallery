<?php
// SAFETY: Boost memory to handle the massive array of 109k files
@ini_set('memory_limit', '1024M'); 
@set_time_limit(300);
error_reporting(E_ALL & ~E_NOTICE);

// --- SECURITY CHECK (Updated path) ---
// We look in the parent directory (../) for the database config
include '../db2.php';

if(!($connection = @ mysqli_connect($hostname,$dbusername,$dbpassword,$dbname)))
    die("Could not connect to database");

if (!isset($_COOKIE["c_username"]) || !isset($_COOKIE["c_password"])) {
    die("You must be logged in to view the gallery.");
}

$usercheck = mysqli_query($connection,"Select * from punter where upper(username) = upper(\"" . $_COOKIE["c_username"] . "\")");
$v_password = "";
while ($usercheckrow = mysqli_fetch_array($usercheck)) {
    $v_password = $usercheckrow["password"];
}

if (md5($v_password) != $_COOKIE["c_password"]) {
    die("Invalid login. Go back and try again.");
}

// Shadowban Indiana
if (isset($_COOKIE["c_id"]) && $_COOKIE["c_id"] == 75) {
    die("Error: Gallery temporarily unavailable. Please try again later.");
}

// Admin Check
$isAdmin = (strtolower($_COOKIE["c_username"]) === 'goldcd');
// ------------------------------------------

// CONFIGURATION
$THUMB_DIR = 'thumbs';       
$CACHE_DIR = 'cache';        
$THUMB_SIZE = 200;           
$PER_PAGE   = 100;           // 100 images per batch
$ALLOWED_EXT = ['jpg', 'jpeg', 'png', 'gif', 'webp'];

// -------------------------------------------------------------------------
// 1. THUMBNAIL GENERATOR
// -------------------------------------------------------------------------
if (isset($_GET['make_thumb'])) {
    $file = basename($_GET['make_thumb']);
    $sourcePath = __DIR__ . '/' . $file;
    $destPath   = __DIR__ . '/' . $THUMB_DIR . '/' . $file;

    // Sanity check
    if (!file_exists($sourcePath) || strpos($file, '.') === 0) {
        header("HTTP/1.0 404 Not Found"); exit;
    }

    if (!is_dir(__DIR__ . '/' . $THUMB_DIR)) {
        mkdir(__DIR__ . '/' . $THUMB_DIR, 0755, true);
    }

    $created = createThumbnail($sourcePath, $destPath, $THUMB_SIZE);

    if ($created) {
        $info = getimagesize($destPath);
        header("Content-Type: " . $info['mime']);
        readfile($destPath);
    } else {
        header("Content-Type: image/jpeg"); 
        readfile($sourcePath); 
    }
    exit;
}

// -------------------------------------------------------------------------
// 1.5 ADMIN DELETE
// -------------------------------------------------------------------------
if (isset($_GET['action']) && $_GET['action'] === 'delete' && isset($_GET['file'])) {
    if (!$isAdmin) {
        die(json_encode(["error" => "Unauthorized"]));
    }
    
    $filename = basename($_GET['file']); // Security
    $srcPath = __DIR__ . '/' . $filename;
    $removedDir = __DIR__ . '/removed';
    $destPath = $removedDir . '/' . $filename;
    $thumbPath = __DIR__ . '/' . $THUMB_DIR . '/' . $filename;
    
    if (!is_dir($removedDir)) mkdir($removedDir, 0755, true);
    
    // 1. Move File
    if (file_exists($srcPath)) {
        rename($srcPath, $destPath);
    }
    
    // 2. Delete Thumbnail
    if (file_exists($thumbPath)) {
        unlink($thumbPath);
    }
    
    // 3. Delete DB Entry
    $safeName = mysqli_real_escape_string($connection, $filename);
    mysqli_query($connection, "DELETE FROM anon_image_tags WHERE filename = '$safeName'");
    
    // 4. Update File Index Cache (Remove from JSON)
    $indexFile = __DIR__ . '/' . $CACHE_DIR . '/file_index.json';
    if (file_exists($indexFile)) {
        $files = json_decode(file_get_contents($indexFile), true);
        if (is_array($files)) {
             // Filter out this file
             $newFiles = array_values(array_filter($files, function($f) use ($filename) {
                 return $f['name'] !== $filename;
             }));
             
             // Save if changed
             if (count($newFiles) != count($files)) {
                 file_put_contents($indexFile, json_encode($newFiles));
             }
        }
    }
    
    echo json_encode(["status" => "ok"]);
    exit;
}

// -------------------------------------------------------------------------

// -------------------------------------------------------------------------
// 2. MAIN LOGIC (Smart Cache)
// -------------------------------------------------------------------------
if (!is_dir(__DIR__ . '/' . $CACHE_DIR)) {
    mkdir(__DIR__ . '/' . $CACHE_DIR, 0755, true);
}

$indexFile = __DIR__ . '/' . $CACHE_DIR . '/file_index.json';
$files = [];

$dirModTime = filemtime(__DIR__); 
$indexModTime = file_exists($indexFile) ? filemtime($indexFile) : 0;
$forceRebuild = isset($_GET['rebuild']);

// SMART CHECK: Only scan if folder is newer than cache, or force rebuild
if ($dirModTime > $indexModTime || !file_exists($indexFile) || $forceRebuild) {
    
    // 1. Load existing index to avoid re-scanning known files
    $files = [];
    $knownFilesMap = [];

    if (file_exists($indexFile) && !$forceRebuild) {
        $loaded = json_decode(file_get_contents($indexFile), true);
        if (is_array($loaded)) {
            $files = $loaded;
            // Create a quick lookup map (Key = Filename) for speed
            foreach ($files as $f) {
                $knownFilesMap[$f['name']] = true;
            }
        }
    }
    
    // 2. Incremental Scan
    $rawFiles = scandir(__DIR__);
    $hasChanges = false;

    foreach ($rawFiles as $f) {
        if ($f === '.' || $f === '..') continue;
        
        // OPTIMIZATION: If we already know this file, skip the expensive filemtime() check
        if (isset($knownFilesMap[$f])) continue;
        
        // New file candidate
        $ext = strtolower(pathinfo($f, PATHINFO_EXTENSION));
        if (in_array($ext, $ALLOWED_EXT)) {
             // Only run filemtime on the NEW file
             if (!is_dir(__DIR__ . '/' . $f)) {
                 $files[] = [ 'name' => $f, 'time' => filemtime(__DIR__ . '/' . $f) ];
                 $hasChanges = true;
             }
        }
    }
    
    // 3. Save only if we actually found new stuff (or forced)
    if ($hasChanges || $forceRebuild || !file_exists($indexFile)) {
        // Sort Newest First
        usort($files, function($a, $b) { 
            return $b['time'] - $a['time']; 
        });

        file_put_contents($indexFile, json_encode($files));
        
        if ($forceRebuild) {
            header("Location: index.php");
            exit;
        }
    }

} else {
    // --- FAST LOAD ---
    $files = json_decode(file_get_contents($indexFile), true);
    if (!is_array($files)) $files = []; 
}

// SEARCH FILTER
$search = isset($_GET['q']) ? trim($_GET['q']) : '';
$type   = isset($_GET['t']) ? $_GET['t'] : 'tag'; // name, tag

if ($search) {
    $filenameMatches = [];
    $tagMatches = [];

    // 1. Search by Filename
    if ($type === 'name') {
        $filenameMatches = array_filter($files, function($item) use ($search) {
            return stripos($item['name'], $search) !== false;
        });
    }

    // 2. Search by Tag (New DB Query)
    if ($type === 'tag') {
        // BOOLEAN SEARCH LOGIC
        // Supports: "tag" (AND), "+tag" (AND), "-tag" (NOT), Quoted: +"multi word"
        $sql = "SELECT filename FROM anon_image_tags WHERE 1=1";
        
        // Regex to find tokens: 
        // 1. Optional + or -
        // 2. Quote string OR non-space sequence
        preg_match_all('/([+-]?)(?:"([^"]*)"|([^\s"]+))/', $search, $matches, PREG_SET_ORDER);
        
        foreach ($matches as $m) {
            $prefix = $m[1];
            $term = !empty($m[2]) ? $m[2] : (isset($m[3]) ? $m[3] : '');
            
            $term = trim($term);
            if (!$term) continue;
            
            $not = ($prefix === '-');
            
            $escaped = mysqli_real_escape_string($connection, $term);
            // Universal Whole Word Regex
            $regex = "(^|[^a-zA-Z0-9])$escaped([^a-zA-Z0-9]|$)";
            
            if ($not) {
                $sql .= " AND tags NOT REGEXP '$regex'";
            } else {
                $sql .= " AND tags REGEXP '$regex'";
            }
        }
        if ($res = mysqli_query($connection, $sql)) {
            while ($row = mysqli_fetch_assoc($res)) {
                $tagMatches[] = $row['filename'];
            }
        }
    }
    
    // 3. Merge Results
    // We need to return an array of file objects. 
    // Let's create a map of all available files for quick lookup
    $filesMap = [];
    foreach ($files as $f) {
        $filesMap[$f['name']] = $f;
    }
    
    $finalList = [];
    
    // Add filename matches
    foreach ($filenameMatches as $f) {
        $finalList[$f['name']] = $f;
    }
    
    // Add tag matches (only if they exist in the file system)
    foreach ($tagMatches as $name) {
        if (isset($filesMap[$name])) {
            $finalList[$name] = $filesMap[$name];
        }
    }
    
    $files = array_values($finalList);
    
    // Re-sort (optional, but keeps consistency)
    usort($files, function($a, $b) { 
        return $b['time'] - $a['time']; 
    });
}

// PAGINATION
$totalImages = count($files);

// Get global tagged count for stats
$taggedResult = mysqli_query($connection, "SELECT count(*) as cnt FROM anon_image_tags");
$totalTagged = 0;
if ($taggedResult && $row = mysqli_fetch_assoc($taggedResult)) {
    $totalTagged = $row['cnt'];
}
$page = isset($_GET['page']) ? (int)$_GET['page'] : 1;
if ($page < 1) $page = 1;
$offset = ($page - 1) * $PER_PAGE;
$displayFiles = array_slice($files, $offset, $PER_PAGE);

// -------------------------------------------------------------------------
// 3. AJAX MODE
// -------------------------------------------------------------------------
if (isset($_GET['ajax'])) {
    if (empty($displayFiles)) {
        exit;
    }
    renderGridItems($displayFiles, $THUMB_DIR);
    exit; 
}

// -------------------------------------------------------------------------
// 4. HELPER FUNCTIONS
// -------------------------------------------------------------------------
function createThumbnail($src, $dest, $targetSize) {
    $info = @getimagesize($src);
    if (!$info) return false;
    $mime = $info['mime'];
    switch ($mime) {
        case 'image/jpeg': $image = imagecreatefromjpeg($src); break;
        case 'image/png':  $image = imagecreatefrompng($src); break;
        case 'image/gif':  $image = imagecreatefromgif($src); break;
        case 'image/webp': $image = imagecreatefromwebp($src); break;
        default: return false;
    }
    if (!$image) return false;
    $width = imagesx($image); $height = imagesy($image);
    $min = min($width, $height);
    $x = ($width - $min) / 2; $y = ($height - $min) / 2;
    $thumb = imagecreatetruecolor($targetSize, $targetSize);
    if ($mime == 'image/png' || $mime == 'image/webp') {
        imagecolortransparent($thumb, imagecolorallocatealpha($thumb, 0, 0, 0, 127));
        imagealphablending($thumb, false);
        imagesavealpha($thumb, true);
    }
    imagecopyresampled($thumb, $image, 0, 0, $x, $y, $targetSize, $targetSize, $min, $min);
    switch ($mime) {
        case 'image/jpeg': imagejpeg($thumb, $dest, 80); break;
        case 'image/png':  imagepng($thumb, $dest); break;
        case 'image/gif':  imagegif($thumb, $dest); break;
        case 'image/webp': imagewebp($thumb, $dest); break;
    }
    imagedestroy($image); imagedestroy($thumb);
    return true;
}

// Helper to pass admin stats to rendering
function renderGridItems($fileList, $thumbDir) {
    global $isAdmin; 
    foreach ($fileList as $file) {
        $filename = $file['name'];
        $urlFilename = rawurlencode($filename);
        $thumbPath = $thumbDir . '/' . $filename;
        $thumbDiskPath = __DIR__ . '/' . $thumbPath;

        if (file_exists($thumbDiskPath)) {
            $imgSrc = rawurlencode($thumbDir) . '/' . $urlFilename;
        } else {
            $imgSrc = "?make_thumb=" . urlencode($filename);
        }
        ?>
        <div class="item">
            <a href="<?php echo $urlFilename; ?>" target="_blank">
                <div class="thumb-box">
                    <img src="<?php echo $imgSrc; ?>" alt="<?php echo htmlspecialchars($filename); ?>" loading="lazy">
                    <?php if ($isAdmin): ?>
                        <div class="delete-btn" onclick="deleteImage('<?php echo htmlspecialchars($filename, ENT_QUOTES); ?>', this); return false;">🗑️</div>
                    <?php endif; ?>
                </div>
            </a>
            <a href="<?php echo $urlFilename; ?>" target="_blank" class="filename" title="<?php echo htmlspecialchars($filename); ?>">
                <?php echo htmlspecialchars($filename); ?>
            </a>
        </div>
        <?php
    }
}
?>

<!DOCTYPE html>
<html>
<head>
    <title>Image Browser</title>
    <meta name="robots" content="noindex">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        body { font-family: sans-serif; background: #f4f4f4; margin: 0; padding: 20px; }
        
        .header { margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; background: white; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); flex-wrap: wrap; gap: 10px; }
        .header h2 { margin: 0; font-size: 18px; }
        .header .meta { font-size: 12px; color: #888; margin-left: 10px; }
        
        .search-box { display: flex; gap: 5px; }
        .search-box input { padding: 8px; border: 1px solid #ddd; border-radius: 4px; width: 150px; }
        .search-box button { padding: 8px 12px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }
        
        .gallery { 
            display: grid; 
            grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); 
            gap: 15px; 
        }
        
        .item { 
            background: white; 
            padding: 10px; 
            border-radius: 8px; 
            box-shadow: 0 2px 5px rgba(0,0,0,0.05); 
            text-align: center; 
            transition: transform 0.2s; 
            animation: fadeIn 0.5s;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }
        .item:hover { transform: translateY(-3px); box-shadow: 0 5px 15px rgba(0,0,0,0.1); }
        
        @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }

        .thumb-box { 
            width: 100%; 
            padding-top: 100%; 
            position: relative; 
            background: #eee; 
            border-radius: 4px; 
            overflow: hidden; 
            margin-bottom: 8px; 
        }
        .thumb-box img { 
            position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover; 
        }
        
        .filename { 
            font-size: 12px; 
            color: #555; 
            text-decoration: none; 
            line-height: 1.3;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
            word-break: break-all;
        }
        
        .status-bar { text-align: center; margin-top: 30px; margin-bottom: 50px; }
        .loader { display: none; color: #666; }
        .spinner { display: inline-block; width: 20px; height: 20px; border: 3px solid rgba(0,0,0,0.1); border-radius: 50%; border-top-color: #007bff; animation: spin 1s ease-in-out infinite; vertical-align: middle; margin-right: 10px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        /* Autocomplete Styles */
        .autocomplete-container { position: relative; display: inline-block; }
        .autocomplete-items {
            position: absolute;
            border: 1px solid #d4d4d4;
            border-bottom: none;
            border-top: none;
            z-index: 99;
            top: 100%;
            left: 0;
            right: 0;
            background-color: #fff;
            max-height: 80vh;
            overflow-y: auto;
            border-radius: 0 0 4px 4px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .autocomplete-items div {
            padding: 8px 10px;
            cursor: pointer;
            border-bottom: 1px solid #d4d4d4;
            text-align: left;
            font-size: 14px;
        }
        .autocomplete-items div:hover {
            background-color: #e9e9e9; 
        }
        .autocomplete-active {
            background-color: #007bff !important; 
            color: #ffffff; 
        }
        
        /* Related Tags Bar */
        .related-tags {
            margin: 10px 0 20px 0;
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .tag-chip {
            background-color: #ffffff;
            border: 1px solid #ced4da;
            border-radius: 16px;
            padding: 0;
            font-size: 13px;
            color: #495057;
            display: flex;
            align-items: center;
            overflow: hidden;
            transition: all 0.2s;
            user-select: none;
            position: relative;
        }
        .tag-chip:hover {
            border-color: #adb5bd;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
        }
        
        /* Inner Sections */
        .chip-label {
            padding: 4px 10px;
            cursor: pointer;
            border-right: 1px solid transparent;
            white-space: nowrap;
        }
        .chip-label:hover { background-color: #f1f3f5; }
        
        /* Buttons Start Hidden (width 0 for anim) */
        .chip-btn {
            padding: 0;
            max-width: 0; /* Use max-width for text transition */
            overflow: hidden;
            cursor: pointer;
            font-weight: bold;
            font-size: 11px; /* Slightly smaller for text pill fit */
            display: flex;
            align-items: center;
            justify-content: center;
            border-left: 1px solid transparent; /* Hide border initially */
            color: #adb5bd;
            transition: all 0.2s ease-out;
            opacity: 0;
            white-space: nowrap;
        }
        
        /* Expansion Logic */
        .tag-chip.expanded {
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            z-index: 10;
        }
        .tag-chip.expanded .chip-btn {
            max-width: 50px; /* Enough for "AND"/"NOT"/"Off" */
            padding: 4px 8px;
            opacity: 1;
            border-left-color: #dee2e6;
        }
        .tag-chip.expanded .chip-btn:hover { background-color: #e9ecef; color: #495057; }
        
        /* Context-Aware Display Logic via CSS */
        /* Neutral: Show + and - */
        .tag-chip:not(.include):not(.exclude).expanded .btn-plus,
        .tag-chip:not(.include):not(.exclude).expanded .btn-minus { max-width: 50px; padding: 4px 8px; opacity: 1; }
        
        /* Include (Green): Show Remove(x) and Exclude(-) */
        .tag-chip.include.expanded .btn-remove,
        .tag-chip.include.expanded .btn-minus { max-width: 50px; padding: 4px 8px; opacity: 1; }
        
        /* Exclude (Red): Show Remove(x) and Include(+) */
        .tag-chip.exclude.expanded .btn-remove,
        .tag-chip.exclude.expanded .btn-plus { max-width: 50px; padding: 4px 8px; opacity: 1; }

        /* Initial Hidden States for wrong context buttons */
        /* Default hides all, the above rules selectively show */
        
        /* State Colors */
        .tag-chip.include { border-color: #c3e6cb; background-color: #d4edda; }
        .tag-chip.include .chip-label { color: #155724; background-color: #d4edda; }
        
        .tag-chip.exclude { border-color: #f5c6cb; background-color: #f8d7da; }
        .tag-chip.exclude .chip-label { color: #721c24; background-color: #f8d7da; }
        
        /* Colorize Buttons */
        .btn-plus { color: #28a745; }
        .btn-minus { color: #dc3545; }
        .btn-remove { color: #6c757d; }
        
        .tag-chip .count {
            font-size: 10px;
            color: #adb5bd;
            margin-left: 4px;
            font-weight: normal;
        }
        
        .delete-btn {
            position: absolute;
            top: 5px;
            right: 5px;
            background: rgba(255, 255, 255, 0.9);
            border-radius: 50%;
            width: 24px;
            height: 24px;
            text-align: center;
            line-height: 24px;
            cursor: pointer;
            z-index: 10;
            font-size: 14px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        }
        .delete-btn:hover {
            background: #ff4d4d;
            color: white;
        }
    </style>
</head>
<body>

<div class="header">
    <div>
        <h2>Mine your youth <span class="meta">(<?php echo number_format($totalImages); ?> files, <?php echo number_format($totalTagged); ?> tagged)</span></h2>
    </div>
    
    <div style="display:flex; gap:10px; align-items:center;">
        <form class="search-box" method="get" autocomplete="off">
            <select name="t" id="searchType" style="border:1px solid #ddd; border-radius:4px; padding:8px;">
                <option value="tag" <?php if($type=='tag') echo 'selected'; ?>>Tag</option>
                <option value="name" <?php if($type=='name') echo 'selected'; ?>>Filename</option>
            </select>
            <div class="autocomplete-container">
                <input type="text" name="q" id="searchInput" value="<?php echo htmlspecialchars($search); ?>" placeholder="Search..." autocomplete="off">
                <div id="autocomplete-list" class="autocomplete-items"></div>
            </div>
            <button type="submit">Go</button>
            <?php if($search): ?><a href="index.php" style="margin-left:5px; align-self:center; font-size:12px;">Clear</a><?php endif; ?>
        </form>
    </div>
    </div>
</div>

<!-- Related Tags Area -->
<div id="relatedTags" class="related-tags" style="display:none;"></div>

<div class="gallery" id="galleryContainer">
    <?php renderGridItems($displayFiles, $THUMB_DIR); ?>
</div>

<div class="status-bar">
    <div class="loader" id="loader">
        <div class="spinner"></div> Loading more...
    </div>
    <div id="endMsg" style="display:none; color:#888;">No more images</div>
</div>

<script>
    var page = 1;
    var isLoading = false;
    var hasMore = true;
    var searchTerm = "<?php echo urlencode($search); ?>";
    var searchType = "<?php echo urlencode($type); ?>";
    var gallery = document.getElementById('galleryContainer');
    var loader = document.getElementById('loader');
    var endMsg = document.getElementById('endMsg');

    window.addEventListener('scroll', function() {
        checkScroll();
    });

    checkScroll();

    function checkScroll() {
        if (isLoading || !hasMore) return;

        var scrollTop = window.scrollY || document.documentElement.scrollTop;
        var windowHeight = window.innerHeight;
        var docHeight = document.documentElement.scrollHeight;
        var distanceToBottom = docHeight - (scrollTop + windowHeight);

        if (distanceToBottom < 2500) {
            loadMore();
        }
    }

    function loadMore() {
        isLoading = true;
        loader.style.display = 'inline-block';
        page++;

        var xhr = new XMLHttpRequest();
        xhr.open('GET', '?ajax=1&page=' + page + '&q=' + searchTerm + '&t=' + searchType, true);
        xhr.onload = function() {
            isLoading = false;
            loader.style.display = 'none';
            if (xhr.status === 200) {
                var content = xhr.responseText.trim();
                if (content.length > 0) {
                    var tempDiv = document.createElement('div');
                    tempDiv.innerHTML = content;
                    while (tempDiv.firstChild) {
                        gallery.appendChild(tempDiv.firstChild);
                    }
                    setTimeout(checkScroll, 100);
                } else {
                    hasMore = false;
                    endMsg.style.display = 'block';
                }
            }
        };
        xhr.onerror = function() {
            isLoading = false;
            loader.style.display = 'none';
        };
        xhr.send();
    }

    var searchTypeSelect = document.getElementById('searchType');
    var searchInput = document.getElementById('searchInput');
    var tagsLoaded = false;
    var allTags = []; // Store raw tags here
    var currentFocus = -1; // Track active item
    
    // --- DROPDOWN LOGIC ---
    function closeAllLists(elmnt) {
        var x = document.getElementsByClassName("autocomplete-items");
        for (var i = 0; i < x.length; i++) {
            if (elmnt != x[i] && elmnt != searchInput) {
                x[i].innerHTML = "";
            }
        }
    }
    
    function addActive(x) {
        if (!x) return false;
        removeActive(x);
        if (currentFocus >= x.length) currentFocus = 0;
        if (currentFocus < 0) currentFocus = (x.length - 1);
        x[currentFocus].classList.add("autocomplete-active");
        // Scroll into view if needed
        x[currentFocus].scrollIntoView({block: "nearest"});
    }
    
    function removeActive(x) {
        for (var i = 0; i < x.length; i++) {
            x[i].classList.remove("autocomplete-active");
        }
    }
    
    function showSuggestions(val) {
        closeAllLists();
        if (!val || searchTypeSelect.value !== 'tag') return false;
        
        currentFocus = -1; // Reset focus
        
        var listDiv = document.getElementById("autocomplete-list");
        listDiv.innerHTML = ''; // connect
        
        var maxItems = 50;
        var count = 0;
        
        for (var i = 0; i < allTags.length; i++) {
           var tag = String(allTags[i]);
           if (tag.toLowerCase().indexOf(val.toLowerCase()) > -1) {
               var item = document.createElement("DIV");
               // Highlight the match
               var startIndex = tag.toLowerCase().indexOf(val.toLowerCase());
               var len = val.length;
               
               var pre = tag.substr(0, startIndex);
               var match = tag.substr(startIndex, len);
               var post = allTags[i].substr(startIndex + len);

               item.innerHTML = pre + "<strong>" + match + "</strong>" + post;
               item.innerHTML += "<input type='hidden' value='" + allTags[i] + "'>";
               
                item.addEventListener("click", function(e) {
                    var val = this.getElementsByTagName("input")[0].value;
                    // Auto-quote if contains spaces
                    if (val.indexOf(' ') > -1) val = '"' + val + '"';
                    
                    searchInput.value = val;
                    closeAllLists();
                    searchInput.form.submit();
                });
               
               listDiv.appendChild(item);
               count++;
               if (count >= maxItems) break;
           }
        }
    }
    
    // KEYBOARD NAVIGATION
    searchInput.addEventListener("keydown", function(e) {
        var listDiv = document.getElementById("autocomplete-list");
        if (listDiv) var x = listDiv.getElementsByTagName("div");
        
        if (e.keyCode == 40) { // DOWN
            currentFocus++;
            addActive(x);
        } else if (e.keyCode == 38) { // UP
            currentFocus--;
            addActive(x);
        } else if (e.keyCode == 13) { // ENTER
            if (currentFocus > -1) {
                if (x) {
                     e.preventDefault(); // Prevent form submit until clicked
                     x[currentFocus].click();
                }
            }
        }
    });
    
    // Input Input Listener
    searchInput.addEventListener("input", function(e) {
        showSuggestions(this.value);
    });
    
    // Click Listener (Show all if empty? or just standard behavior)
    searchInput.addEventListener("click", function(e) {
         if (this.value && searchTypeSelect.value === 'tag') {
             showSuggestions(this.value);
         }
    });

    // Close on outside click
    document.addEventListener("click", function (e) {
        closeAllLists(e.target);
    });


    function checkTagMode() {
        if (searchTypeSelect.value === 'tag') {
            loadTags();
        }
    }

    function loadTags(force) {
        if (tagsLoaded && !force) return;
        
        var url = 'api.php?action=get_tags';
        if (force) url += '&rebuild=1';



        var xhr = new XMLHttpRequest();
        xhr.open('GET', url, true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    allTags = JSON.parse(xhr.responseText); // Store in global array
                    console.log("Loaded tags: " + allTags.length);
                    tagsLoaded = true;
                } catch(e) { console.error("Error parsing tags", e); }
            }
        };
        xhr.send();
    }
    
    function deleteImage(filename, btnElement) {
        // Instant Feedback: Remove grid item immediately
        var gridItem = btnElement.closest('.item');
        if (gridItem) {
            gridItem.style.opacity = '0';
            setTimeout(function() { gridItem.remove(); }, 200);
        }
        
        // Fire and forget
        fetch('?action=delete&file=' + encodeURIComponent(filename));
    }

    searchTypeSelect.addEventListener('change', checkTagMode);
    
    // Init on load
    searchTypeSelect.addEventListener('change', checkTagMode);
    
    // Init on load
    checkTagMode();
    
    // --- Related Tags Logic ---
    function loadRelatedTags() {
        var query = "<?php echo addslashes($search); ?>";
        if (!query || searchTypeSelect.value !== 'tag') return;
        
        // 1. Parse Current State from Query String (Regex for Quotes)
        // Map: tag -> state ('include', 'exclude')
        var activeState = {}; 
        // Regex: Match optional +/- then (active state) then Quoted String OR Word
        var regex = /([+-]?)(?:"([^"]*)"|([^\s"]+))/g;
        var match;
        
        while ((match = regex.exec(query)) !== null) {
            var prefix = match[1];
            var term = match[2] || match[3];
            if (!term) continue;
            term = term.toLowerCase();
            
            if (prefix === '-') activeState[term] = 'exclude';
            else activeState[term] = 'include'; // word or +word is include
        }
        
        var url = 'api.php?action=get_related_tags&q=' + encodeURIComponent(query);
        
        var xhr = new XMLHttpRequest();
        xhr.open('GET', url, true);
        xhr.onload = function() {
            if (xhr.status === 200) {
                try {
                    var apiTags = JSON.parse(xhr.responseText);
                    var container = document.getElementById('relatedTags');
                    
                    // 2. Merge Lists
                    var displayList = [];
                    var seen = {};
                    
                    // Add Active First
                    for (var t in activeState) {
                        displayList.push({ tag: t, state: activeState[t], count: apiTags[t] || '' });
                        seen[t] = true;
                    }
                    
                    // Add API Suggestions
                    for (var t in apiTags) {
                        if (!seen[t]) {
                            displayList.push({ tag: t, state: 'neutral', count: apiTags[t] });
                            seen[t] = true;
                        }
                    }
                    
                    if (displayList.length > 0) {
                        var html = '<span style="font-size:12px; color:#adb5bd; align-self:center; margin-right:5px; font-weight:600;">REFINE:</span>';
                        
                        displayList.forEach(function(item) {
                            var cls = 'tag-chip';
                            if(item.state === 'include') cls += ' include';
                            if(item.state === 'exclude') cls += ' exclude';
                            
                            // HTML Structure: [ Label | + | - | x ]
                            // Buttons hidden by CSS unless expanded
                            html += '<div class="' + cls + '" data-tag="' + item.tag + '">' + 
                                        '<span class="chip-label">' + item.tag + (item.count ? ' <span class="count">' + item.count + '</span>' : '') + '</span>' +
                                        '<span class="chip-btn btn-remove" title="Remove (Unselect)">✕</span>' +
                                        '<span class="chip-btn btn-plus" title="Include (+)">AND</span>' +
                                        '<span class="chip-btn btn-minus" title="Exclude (-)">NOT</span>' +
                                    '</div>';
                        });
                        
                        // Use Text "Is" "AND" "NOT" instead of icons for clarity in split pill?
                        // User said "show the two options we can switch to (out of unselected, 'and', 'not')"
                        // I will use text abbreviations: "Is" (Neutral?), "AND", "NOT". Or icons + text?
                        // Let's stick to simple text for the pill buttons as requested implicitly by "unselected, and, not"
                        // Updating HTML above to use text. "Is" might be confusing. "Clear"? "X"?
                        // Let's use "X" icon for remove, "AND" text, "NOT" text?
                        // Re-writing HTML generation block above with user's words.
                        
                        container.innerHTML = html;
                        container.style.display = 'flex';
                        
                        // 3. Logic
                        function updateState(tag, newState) {
                            var nextStateMap = Object.assign({}, activeState); // Copy
                            
                            if (newState === 'neutral') delete nextStateMap[tag];
                            else nextStateMap[tag] = newState;
                            
                            var finalStr = "";
                            for (var t in nextStateMap) {
                                var token = t;
                                if (token.indexOf(' ') > -1) token = '"' + token + '"'; 
                                
                                if(nextStateMap[t] === 'exclude') finalStr += "-" + token + " ";
                                else finalStr += "+" + token + " ";
                            }
                            
                            searchInput.value = finalStr.trim();
                            searchInput.form.submit();
                        }

                        var chips = container.getElementsByClassName('tag-chip');
                        for (var i=0; i<chips.length; i++) {
                            // Label Click -> Toggle Expand
                            chips[i].querySelector('.chip-label').addEventListener('click', function(e) {
                                e.stopPropagation();
                                var parent = this.closest('.tag-chip');
                                var wasExpanded = parent.classList.contains('expanded');
                                
                                // Close all others
                                var all = container.getElementsByClassName('tag-chip');
                                for(var j=0; j<all.length; j++) all[j].classList.remove('expanded');
                                
                                if (!wasExpanded) parent.classList.add('expanded');
                            });
                            
                            // Plus (AND)
                            chips[i].querySelector('.btn-plus').addEventListener('click', function(e) {
                                e.stopPropagation();
                                updateState(this.closest('.tag-chip').getAttribute('data-tag'), 'include');
                            });

                            // Minus (NOT)
                            chips[i].querySelector('.btn-minus').addEventListener('click', function(e) {
                                e.stopPropagation();
                                updateState(this.closest('.tag-chip').getAttribute('data-tag'), 'exclude');
                            });
                            
                             // Remove (Unselect)
                            chips[i].querySelector('.btn-remove').addEventListener('click', function(e) {
                                e.stopPropagation();
                                updateState(this.closest('.tag-chip').getAttribute('data-tag'), 'neutral');
                            });
                        }
                        
                        // Global Click -> Close All
                        document.addEventListener('click', function(e) {
                            if (!e.target.closest('.tag-chip')) {
                                var all = container.getElementsByClassName('tag-chip');
                                for(var j=0; j<all.length; j++) all[j].classList.remove('expanded');
                            }
                        });
                    }
                } catch(e) { console.error(e); }
            }
        };
        xhr.send();
    }

    
    // Run if searching
    var currentSearch = <?php echo json_encode($search); ?>;
    if (currentSearch) loadRelatedTags();

</script>

</body>
</html>