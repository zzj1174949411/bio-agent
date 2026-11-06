args <- commandArgs(trailingOnly = TRUE)

fail_run <- function(error) {
  cat(
    paste0("DESEQ2_RUN_ERROR: ", conditionMessage(error), "\n"),
    file = stderr()
  )
  quit(save = "no", status = 1L, runLast = FALSE)
}

runner_stop <- function(code, message) {
  stop(paste0(code, ": ", message), call. = FALSE)
}

tryCatch({
  if (length(args) != 1L || !nzchar(args[[1L]])) {
    runner_stop("INVALID_PARAMETER_COUNT", "exactly one JSON parameter file path is required")
  }
  parameter_path <- normalizePath(args[[1L]], winslash = "/", mustWork = TRUE)
  parameters <- jsonlite::fromJSON(
    parameter_path,
    simplifyVector = FALSE,
    simplifyDataFrame = FALSE
  )
  allowed_fields <- c(
    "counts_path", "metadata_path", "output_dir", "factor",
    "numerator", "denominator", "alpha", "lfc_shrink"
  )
  if (!is.list(parameters) || is.null(names(parameters)) ||
      !identical(sort(names(parameters)), sort(allowed_fields))) {
    runner_stop(
      "INVALID_PARAMETER_SCHEMA",
      "parameter JSON fields must exactly match the DESeq2 whitelist"
    )
  }

  script_file <- grep("^--file=", commandArgs(), value = TRUE)
  if (length(script_file) != 1L) {
    runner_stop("INVALID_ENTRYPOINT", "runner must be invoked as a fixed Rscript file")
  }
  script_path <- normalizePath(
    sub("^--file=", "", script_file[[1L]]),
    winslash = "/",
    mustWork = TRUE
  )
  project_root <- normalizePath(
    file.path(dirname(script_path), "..", ".."),
    winslash = "/",
    mustWork = TRUE
  )
  root_prefix <- paste0(tolower(project_root), "/")

  scalar_string <- function(value, field) {
    if (!is.character(value) || length(value) != 1L || !nzchar(value)) {
      runner_stop("INVALID_PARAMETER_TYPE", paste0(field, " must be one non-empty string"))
    }
    value[[1L]]
  }
  resolve_project_path <- function(value, field, must_work) {
    value <- scalar_string(value, field)
    if (grepl("^(?:[A-Za-z]:[\\\\/]|[\\\\/]{1,2})", value, perl = TRUE)) {
      runner_stop("INVALID_PATH", paste0(field, " must be relative to the project root"))
    }
    resolved <- normalizePath(
      file.path(project_root, value),
      winslash = "/",
      mustWork = must_work
    )
    if (!identical(tolower(resolved), tolower(project_root)) &&
        !startsWith(tolower(resolved), root_prefix)) {
      runner_stop("INVALID_PATH", paste0(field, " resolves outside the project root"))
    }
    resolved
  }

  counts_path <- resolve_project_path(parameters$counts_path, "counts_path", TRUE)
  metadata_path <- resolve_project_path(parameters$metadata_path, "metadata_path", TRUE)
  output_dir <- resolve_project_path(parameters$output_dir, "output_dir", FALSE)
  factor_name <- scalar_string(parameters$factor, "factor")
  numerator <- scalar_string(parameters$numerator, "numerator")
  denominator <- scalar_string(parameters$denominator, "denominator")
  alpha <- parameters$alpha
  if (!is.numeric(alpha) || length(alpha) != 1L || !is.finite(alpha) ||
      alpha <= 0 || alpha >= 1) {
    runner_stop("INVALID_ALPHA", "alpha must be one finite number in (0, 1)")
  }
  lfc_shrink <- parameters$lfc_shrink
  if (!is.logical(lfc_shrink) || length(lfc_shrink) != 1L || is.na(lfc_shrink)) {
    runner_stop("INVALID_SHRINK_OPTION", "lfc_shrink must be one boolean")
  }

  counts_data <- utils::read.csv(
    counts_path,
    check.names = FALSE,
    stringsAsFactors = FALSE
  )
  if (ncol(counts_data) < 2L || !identical(names(counts_data)[[1L]], "feature_id")) {
    runner_stop("INVALID_COUNTS_FILE", "counts CSV must begin with a feature_id column")
  }
  feature_ids <- as.character(counts_data[[1L]])
  sample_ids <- names(counts_data)[-1L]
  numeric_values <- suppressWarnings(as.numeric(unlist(counts_data[-1L], use.names = FALSE)))
  counts <- matrix(
    numeric_values,
    nrow = nrow(counts_data),
    ncol = length(sample_ids),
    dimnames = list(feature_ids, sample_ids)
  )
  metadata <- utils::read.csv(
    metadata_path,
    check.names = FALSE,
    stringsAsFactors = FALSE
  )

  source(file.path(dirname(script_path), "functions.R"), local = FALSE)
  result <- run_deseq2(
    counts = counts,
    metadata = metadata,
    factor = factor_name,
    numerator = numerator,
    denominator = denominator,
    alpha = alpha,
    lfc_shrink = lfc_shrink
  )
  paths <- write_deseq2_outputs(result, output_dir)
  cat(jsonlite::toJSON(paths, auto_unbox = FALSE), "\n")
}, error = fail_run)
