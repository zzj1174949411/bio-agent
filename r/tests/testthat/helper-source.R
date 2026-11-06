helper_path <- tryCatch(sys.frame(1)$ofile, error = function(error) NULL)
search_path <- if (!is.null(helper_path)) {
  dirname(normalizePath(helper_path, winslash = "/", mustWork = TRUE))
} else {
  normalizePath(getwd(), winslash = "/", mustWork = TRUE)
}

project_root <- NULL
for (iteration in seq_len(10L)) {
  candidate <- file.path(search_path, "r", "deseq2", "functions.R")
  if (file.exists(candidate)) {
    project_root <- search_path
    break
  }
  parent <- dirname(search_path)
  if (identical(parent, search_path)) {
    break
  }
  search_path <- parent
}

if (is.null(project_root)) {
  stop("Could not locate the Bio-Agent project root", call. = FALSE)
}

source(
  file.path(project_root, "r", "deseq2", "functions.R"),
  local = FALSE
)
