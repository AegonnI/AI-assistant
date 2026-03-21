import sys


def main() -> None:
    try:
        import torch
    except Exception as e:
        print("IMPORT_TORCH_ERROR:", repr(e))
        sys.exit(1)

    print("python:", sys.version.replace("\n", " "))
    print("torch:", getattr(torch, "__version__", "unknown"))
    print("torch_cuda_version:", getattr(getattr(torch, "version", None), "cuda", None))
    try:
        available = bool(torch.cuda.is_available())
    except Exception as e:
        print("cuda_is_available_error:", repr(e))
        sys.exit(1)

    print("cuda_available:", available)
    try:
        count = torch.cuda.device_count() if available else 0
    except Exception as e:
        print("cuda_device_count_error:", repr(e))
        sys.exit(1)

    print("device_count:", count)
    if available and count > 0:
        try:
            print("device0:", torch.cuda.get_device_name(0))
        except Exception as e:
            print("get_device_name_error:", repr(e))


if __name__ == "__main__":
    main()

